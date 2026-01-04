from flask import session, jsonify, request, redirect, url_for, flash
from datetime import datetime, timedelta
from functools import wraps

# ============================================
# 配置与常量
# ============================================
EXPIRE_HOURS = 24


def check_login_status():
    """
    检查用户是否登录以及 Session 是否过期
    返回: (bool, response) 
    - True, None: 验证通过
    - False, Response: 验证失败，返回需要执行的 return 语句
    """
    user_id = session.get("user_id")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # 1. 检查 Session 是否存在
    if not user_id:
        if is_ajax:
            return False, jsonify({"code": 401, "msg": "登录已过期，请重新登录", "redirect_url": url_for("login.login")})
        return False, redirect(url_for("login.login"))

    # 2. 检查 Session 是否过期
    last_active = session.get("last_active")
    if last_active:
        try:
            last_dt = datetime.strptime(last_active, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_dt > timedelta(hours=EXPIRE_HOURS):
                session.clear()
                if is_ajax:
                    return False, jsonify({"code": 401, "msg": "会话已超时", "redirect_url": url_for("login.login")})
                flash("会话已超时，请重新登录", "error")
                return False, redirect(url_for("login.login"))
        except ValueError:
            session.clear()
            return False, redirect(url_for("login.login"))

    # 3. 续期
    session["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return True, None

# ============================================
# 装饰器
# ============================================

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        is_valid, response = check_login_status()
        if not is_valid:
            return response
        return f(*args, **kwargs)
    return wrapper

def permission_required(*allowed_roles):
    """
    角色权限验证装饰器 (集合交集判断)
    :param allowed_roles: 该路由允许的角色列表，例如 "SA", "GA"
    使用方式: @permission_required("SA", "GA")
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

            # 1. 先执行登录检查
            is_valid, response = check_login_status()
            if not is_valid:
                return response

            # 2. 获取用户当前的角色
            user_role_str = session.get("role", "")
            
            if user_role_str:
                user_roles = set(r.strip() for r in user_role_str.split(',') if r.strip())
            else:
                user_roles = set()
            
            # 3. 获取允许的角色集合
            required_roles = set(allowed_roles)

            # 4. 核心逻辑：计算交集 (只要命中一个允许的角色即可)
            if not (user_roles & required_roles):
                msg = "权限不足，无法访问该资源"
                if is_ajax:
                    return jsonify({"code": 403, "msg": msg}), 403
                
                flash(msg, "error")
                referer = request.referrer
                current_url = request.url
                
                # 跳回上一页，防止死循环
                if referer and referer != current_url:
                    return redirect(referer)
                else:
                    return redirect(url_for("login.login")) 

            # 5. 前端特殊权限检查 (可选)
            if request.headers.get("X-Check-Perm"):
                 return jsonify({"code": 200, "msg": "权限验证通过"})

            return f(*args, **kwargs)
        return wrapper
    return decorator