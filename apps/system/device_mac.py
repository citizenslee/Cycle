# device_mac.py 医院管理界面
from flask import render_template, request, jsonify ,session
from .route import bp_system 
from apps.tools.auth import login_required, permission_required
from apps.tools.db import query_db,modify_db



@bp_system.route("/device_test")
def dindex():
    return render_template("system/user_devices.html")

@bp_system.route("/device_info", methods=["POST"])
def device_info():
    # 从 session 里取当前登录用户信息
    user_info = {
        "user_id": session.get("user_id"),
        "username": session.get("username"),
        "role": session.get("role"),
        "id_hospital": session.get("id_hospital"),
        "id_department": session.get("id_department"),
        "hospital_name": session.get("hospital_name", "未设置"),
        "department_name": session.get("department_name", "未设置")
    }

    data = request.json or {}
    print("前端设备信息：", data)

    info = {
        "ip": request.remote_addr,
        "device_id": data.get("device_id"),
        "user": user_info
    }

    return jsonify(info)