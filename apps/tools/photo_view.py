# photo_view.py
from flask import Blueprint, send_from_directory, abort, current_app
import os

bp_photo_view = Blueprint("photo_view", __name__)

@bp_photo_view.route('/uploads/<folder>/<path:filename>')
def serve_uploads(folder, filename):
    """
    folder: 只能是 'report' 或 'finish'
    """
    if folder not in ['report', 'finish']:
        abort(404)
        
    # 构建绝对路径： 项目根目录/uploads/report 或 finish
    upload_dir = os.path.join(current_app.root_path, 'uploads', folder)
    
    if not os.path.exists(os.path.join(upload_dir, filename)):
        abort(404)

    return send_from_directory(upload_dir, filename)


# ================= vendor_photo =================
@bp_photo_view.route('/vendor_photo/<path:filename>')
def vendor_photo(filename):
    vendor_dir = os.path.join(current_app.root_path, 'vendor_photo')
    file_path = os.path.join(vendor_dir, filename)

    if not os.path.isfile(file_path):
        abort(404)

    return send_from_directory(vendor_dir, filename)
