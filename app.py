from flask import Flask, request, send_file, jsonify
import os
import tempfile
import io
from pdf_compressor import compress_pdf

try:
    import fitz  # PyMuPDF
    from PIL import Image
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ==== PRESET KOMPRESI (dari ringan → mini) ====
# engine 'pdf'    : pakai pdf_compressor — teks tetap searchable
# engine 'raster' : pakai PyMuPDF rasterize — teks jadi gambar, ukuran jauh lebih kecil
PRESETS = {
    'ringan': {
        'label': 'Ringan — kualitas hampir sama',
        'engine': 'pdf',
        'params': {'level': 1, 'quality': 75, 'max_dim': 2000},
        'estimasi': '30-50%',
        'searchable': True,
    },
    'seimbang': {
        'label': 'Seimbang — untuk sehari-hari',
        'engine': 'pdf',
        'params': {'level': 2, 'quality': 60, 'max_dim': 1500},
        'estimasi': '50-70%',
        'searchable': True,
    },
    'kuat': {
        'label': 'Kuat — untuk upload online',
        'engine': 'pdf',
        'params': {'level': 3, 'quality': 45, 'max_dim': 1200},
        'estimasi': '70-85%',
        'searchable': True,
    },
    'ekstrem': {
        'label': 'Ekstrem — teks jadi gambar, kualitas masih tajam',
        'engine': 'raster',
        'params': {'dpi': 150, 'quality': 60},
        'estimasi': '80-90%',
        'searchable': False,
    },
    'ultra': {
        'label': 'Ultra — prioritas ukuran kecil',
        'engine': 'raster',
        'params': {'dpi': 100, 'quality': 40},
        'estimasi': '90-95%',
        'searchable': False,
    },
    'mini': {
        'label': 'Mini — ukuran paling kecil, kualitas minimal',
        'engine': 'raster',
        'params': {'dpi': 72, 'quality': 25},
        'estimasi': '95%+',
        'searchable': False,
    },
}
DEFAULT_PRESET = 'kuat'


def compress_raster(input_path, output_path, dpi=100, quality=40):
    """Rasterize setiap halaman ke JPEG resolusi rendah, bungkus ulang jadi PDF."""
    src = fitz.open(input_path)
    dst = fitz.open()

    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)

        new_page = dst.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buf.getvalue())

    dst.save(output_path, deflate=True, garbage=4)
    dst.close()
    src.close()


@app.route('/')
def index():
    return "API Emanskies Compress aktif. POST /compress (file, preset)"


@app.route('/presets', methods=['GET'])
def list_presets():
    return jsonify({
        'default': DEFAULT_PRESET,
        'pymupdf_available': HAS_PYMUPDF,
        'presets': {
            k: {
                'label': v['label'],
                'estimasi': v['estimasi'],
                'searchable': v['searchable'],
            } for k, v in PRESETS.items()
        }
    })


@app.route('/compress', methods=['POST'])
def compress():
    if 'file' not in request.files:
        return jsonify({'error': 'Tidak ada file'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Nama file kosong'}), 400

    preset_name = request.form.get('preset', DEFAULT_PRESET)
    if preset_name not in PRESETS:
        return jsonify({
            'error': f'Preset tidak dikenal: {preset_name}',
            'pilihan': list(PRESETS.keys())
        }), 400

    preset = PRESETS[preset_name]

    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', dir=UPLOAD_FOLDER)
    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', dir=UPLOAD_FOLDER)
    tmp_in.close(); tmp_out.close()
    file.save(tmp_in.name)

    try:
        orig_size = os.path.getsize(tmp_in.name)

        if preset['engine'] == 'raster' and HAS_PYMUPDF:
            compress_raster(tmp_in.name, tmp_out.name, **preset['params'])
        elif preset['engine'] == 'raster':
            # Fallback kalau PyMuPDF tidak terinstall
            compress_pdf(tmp_in.name, tmp_out.name, level=3, quality=20, max_dim=800)
        else:
            compress_pdf(tmp_in.name, tmp_out.name, **preset['params'])

        new_size = os.path.getsize(tmp_out.name)

        response = send_file(
            tmp_out.name,
            as_attachment=True,
            download_name=f'emanskies-{preset_name}.pdf',
            mimetype='application/pdf'
        )
        response.headers['X-Original-Size'] = str(orig_size)
        response.headers['X-Compressed-Size'] = str(new_size)
        response.headers['X-Preset'] = preset_name
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_in.name):
            os.unlink(tmp_in.name)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)