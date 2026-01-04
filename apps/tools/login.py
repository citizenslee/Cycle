from flask import Blueprint, session, jsonify, request, redirect, render_template
from werkzeug.security import check_password_hash
from datetime import datetime
from apps.tools.db import query_db, modify_db
from PIL import Image, ImageDraw
import random
import io
import os
import base64
from apps.tools.permissions import ROLE_LEVELS, get_user_role_name


bp_login = Blueprint("login", __name__, url_prefix="/login")

# =========================================================
# 内部辅助函数
# =========================================================

def establish_user_session(user):
    """统一设置用户 Session 逻辑"""
    session.clear()
    session.permanent = True  # 开启持久化会话
    session["user_id"] = user['id']
    session["username"] = user['username']
    session["role"] = user['role']
    session["id_hospital"] = user["id_hospital"]
    session["id_department"] = user["id_department"]
    session["hospital_name"] = user["hospital_name"] or "未知单位"
    session["department_name"] = user["department_name"] or "未知部门"
    session["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def sync_user_device_id(user_id, device_id):
    """更新用户的设备列表（最多保留最后8个）"""
    if not device_id: return

    user = query_db("SELECT user_devices_id FROM user WHERE id = ?", (user_id,), one=True)
    current_ids_str = user['user_devices_id'] if user and user['user_devices_id'] else ""
    
    # 清洗现有的 ID 列表
    id_list = [d.strip() for d in current_ids_str.split(',') if d.strip()]

    if device_id not in id_list:
        id_list.append(device_id)
        if len(id_list) > 8:
            id_list = id_list[-8:]
        new_ids_str = ",".join(id_list)
        modify_db("UPDATE user SET user_devices_id = ? WHERE id = ?", (new_ids_str, user_id))

def get_user_with_info(username_or_id, is_id=False):
    """统一获取带医院/部门信息的查询"""
    field = "u.id" if is_id else "u.username"
    sql = f"""
        SELECT u.*, h.hospital_name, d.department_name
        FROM user u
        LEFT JOIN hospital h ON u.id_hospital = h.id_hospital
        LEFT JOIN department d ON u.id_department = d.id_department
        WHERE {field} = ?
    """
    return query_db(sql, (username_or_id,), one=True)

# ============================================
# 验证码逻辑
# ============================================

def generate_slide_image():
    width, height = 280, 150 
    piece_w, piece_h = 50, 50 

    # 路径处理
    base_dir = os.path.join('static', 'photo', 'yzm')
    if not os.path.exists(base_dir):
        # 如果目录不存在，返回纯色块防止崩溃
        img = Image.new('RGB', (width, height), (70, 130, 180))
    else:
        files = [f for f in os.listdir(base_dir) if f.endswith(('.png', '.jpg', '.jpeg'))]
        img_path = os.path.join(base_dir, random.choice(files)) if files else None
        
        try:
            image = Image.open(img_path).convert('RGB')
            orig_w, orig_h = image.size
            scale = min(width / orig_w, height / orig_h)
            new_w, new_h = int(orig_w * scale), int(orig_h * scale)
            image_resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            img = Image.new('RGB', (width, height), (40, 44, 52)) # 深色画布匹配登录页
            img.paste(image_resized, ((width - new_w) // 2, (height - new_h) // 2))
        except:
            img = Image.new('RGB', (width, height), (70, 130, 180))

    target_x = random.randint(piece_w + 20, width - piece_w - 20)
    target_y = random.randint(10, height - piece_h - 10)

    # 抠图并加高亮边缘
    piece_image = img.crop((target_x, target_y, target_x + piece_w, target_y + piece_h))
    draw = ImageDraw.Draw(piece_image)
    draw.rectangle((0, 0, piece_w-1, piece_h-1), outline=(255, 255, 255, 150), width=2)

    # 原图缺口处理
    mask = Image.new('RGBA', (piece_w, piece_h), (0, 0, 0, 150))
    img.paste(mask, (target_x, target_y), mask)

    def to_base64(image, fmt='JPEG'):
        buf = io.BytesIO()
        image.save(buf, format=fmt)
        return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()

    return to_base64(img), to_base64(piece_image, 'PNG'), target_y, target_x

@bp_login.route('/slide_data')
def get_slide_data():
    bg_b64, piece_b64, piece_y, target_x = generate_slide_image()
    session['slide_target_x'] = target_x
    session['slide_verified'] = False 
    return jsonify({
        "code": 0, "bg_image": bg_b64, "piece_image": piece_b64, 
        "piece_y": piece_y, "image_width": 280
    })

@bp_login.route('/verify_slide', methods=['POST'])
def verify_slide():
    user_x = request.json.get('x')
    target_x = session.get('slide_target_x')
    
    if target_x is None or user_x is None:
        return jsonify({"code": 1, "msg": "请重新刷新验证码"})
    
    # 允许 6 像素误差
    if abs(float(user_x) - float(target_x)) < 6:
        session['slide_verified'] = True
        return jsonify({"code": 0, "msg": "验证通过"})
    
    session['slide_verified'] = False
    return jsonify({"code": 1, "msg": "验证失败"})

# =========================================================
# 登录路由
# =========================================================

@bp_login.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"): return redirect("/")
        return render_template("login.html")

    # 安全检查
    if not session.pop('slide_verified', False): # 使用 pop 确保验证状态只能用一次
        return jsonify({"code": 1, "msg": "验证安全环境失败，请重试"})

    username = request.form.get("username")
    password = request.form.get("password")
    device_id = request.form.get('device_id') # 统一参数名

    user = get_user_with_info(username)
    
    if user and check_password_hash(user['password'], password):
        establish_user_session(user)
        sync_user_device_id(user['id'], device_id)
        return jsonify({"code": 0, "msg": "登录成功", "redirect_url": "/"})
    
    return jsonify({"code": 1, "msg": "账号或密码错误", "need_refresh": True})

@bp_login.route("/check_device", methods=["POST"])
def check_device():
    device_id = request.json.get('device_id')
    if not device_id:
        return jsonify({"code": 1, "msg": "无效参数"})
    
    # 查找所有绑定了该设备 ID 的用户
    # 注意：这里 user_devices_id 也是逗号分隔的字符串，使用 LIKE 做模糊查询初步筛选
    sql = """
        SELECT u.id, u.username, u.role, u.user_devices_id, 
               h.hospital_name, d.department_name
        FROM user u
        LEFT JOIN hospital h ON u.id_hospital = h.id_hospital
        LEFT JOIN department d ON u.id_department = d.id_department
        WHERE u.user_devices_id LIKE ?
    """
    rows = query_db(sql, (f"%{device_id}%",))
    
    accounts = []
    for row in rows:
        # 1. 精确匹配设备ID (防止 device_id="1" 匹配到 "12")
        stored_devices = [d.strip() for d in (row['user_devices_id'] or "").split(',') if d.strip()]
        
        if device_id in stored_devices:
            # 2. 获取用户角色字符串 (e.g., "DA,SE")
            role_str = row['role']
            
            # 3. 计算最高权限角色的中文名
            # 如果你在 permissions.py 里加了 get_user_role_name 方法：
            role_display = get_user_role_name(role_str)
        

            accounts.append({
                "id": row['id'],
                "username": row['username'],
                "role_name": role_display, # 显示计算后的最高角色中文名
                "hospital": row['hospital_name'] or "未关联单位",
                "department": row['department_name'] or "未关联部门"
            })
    
    return jsonify({"code": 0, "accounts": accounts}) if accounts else jsonify({"code": 1, "msg": "新设备"})

@bp_login.route("/fast_login", methods=["POST"])
def fast_login():
    data = request.json or {}
    device_id = data.get('device_id')
    user_id = data.get('user_id')

    # ... 查询逻辑 ...
    user = get_user_with_info(user_id, is_id=True)
    
    if user:
        stored_ids = [d.strip() for d in (user['user_devices_id'] or "").split(',') if d.strip()]
        if device_id in stored_ids:
            establish_user_session(user)
            # --- 必须包含 user 对象，前端 verifyHospital 才能读取到 ---
            return jsonify({
                "code": 0, 
                "msg": "验证成功",
                "user": {
                    "username": user['username'],
                    "hospital": user['hospital_name'] or "未设置",
                    "id_hospital": user['id_hospital'],  # 确保这里是 id_hospital 而不是 hospital_id
                    "department": user['department_name'] or "未设置"
                }
            })

# 同理修改 fast_login 接口中的返回字段
    
    return jsonify({"code": 1, "msg": "认证失效"})

@bp_login.route("/api_login_and_bind", methods=["POST"])
def api_login_and_bind():
    """用于巡检页等弹出式登录并绑定的接口"""
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    device_id = data.get('device_id') or data.get('user_device_id') # 兼容旧参数名

    user = get_user_with_info(username)

    if user and check_password_hash(user['password'], password):
        establish_user_session(user)
        if device_id:
            sync_user_device_id(user['id'], device_id)

        return jsonify({
            "code": 0, 
            "msg": "验证成功",
            "user": {
                "username": user['username'],
                "hospital": user['hospital_name'] or "未设置",
                "id_hospital": user['id_hospital'],  # 确保这里是 id_hospital 而不是 hospital_id
                "department": user['department_name'] or "未设置"
            }
        })

    return jsonify({"code": 1, "msg": "账号或密码错误"})

@bp_login.route("/logout")
def logout():
    session.clear()
    return redirect("/login/login")