# report.py 报单界面
import os
import random
from datetime import datetime
from flask import render_template, request, jsonify
# 引入数据库工具
from apps.tools.db import query_db, modify_db,execute_transaction
# 引入AI模块
from apps.tools.deepseekapi import get_ai_suggestion
from .route import bp_orders
from .orders_log import record_order_flow
# 引入权限工具
from apps.tools.permissions import get_current_user_info
from apps.tools.auth import login_required

# 基础上传路径
BASE_UPLOAD_FOLDER = 'uploads'
REPORT_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, 'report')
FINISH_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, 'finish')

# 确保文件夹存在
for folder in [REPORT_FOLDER, FINISH_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

def save_upload_photos(files, work_id, type_label, target_folder):
    """
    通用图片保存函数
    :param files: request.files.getlist('photos[]')
    :param work_id: 工单ID
    :param type_label: 标签名 (report 或 finish)
    :param target_folder: 目标物理路径
    :return: 逗号分隔的文件名字符串
    """
    photo_names = []
    if not files:
        return ""
    
    for idx, file in enumerate(files, start=1):
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            # 统一命名: 工单号_类型_序号.后缀 (例如: WO001_report_1.jpg)
            filename = f"{work_id}_{type_label}_{idx}{ext}"
            filepath = os.path.join(target_folder, filename)
            
            file.save(filepath)
            photo_names.append(filename)
            
    return ",".join(photo_names)        

@bp_orders.route('/report')
# -------------------------------------------------------
# 报修页面（扫码进入）
# -------------------------------------------------------
def report():
    dept_code = request.args.get("url")
    if not dept_code:
        return "<h3 style='text-align:center;margin-top:50px;'>⚠ 非法访问，请使用医院提供的二维码扫码进入</h3>"
    try:
        # 使用 query_db 查询部门是否存在
        sql = "SELECT department_name FROM department WHERE department_url=?"
        row = query_db(sql, (dept_code,), one=True)
        
        if not row:
            return "<h3 style='text-align:center;margin-top:50px;'>⚠ 无效二维码，请联系后勤科</h3>"
    except Exception as e:
        print(f"Report page error: {e}")
        return "<h3 style='text-align:center;margin-top:50px;'>⚠ 内部错误，请稍后再试</h3>"
    
    return render_template("orders/report.html", dept_code=dept_code)


@bp_orders.route('/submit_report', methods=['POST'])
def submit_report():
    try:
        # 1. 获取基础参数
        demand = request.form.get('demand')
        contact_phone = request.form.get('contact_phone')
        dept_code = request.form.get('dept_code', '') 
        
        if not demand:
            return jsonify({"code": 1, "msg": "缺少必要字段"})

        # 2. 查询发起科室信息 (只读操作，不放入事务)
        dept_row = query_db(
            "SELECT id_department, id_hospital, department_name FROM department WHERE department_url=?", 
            (dept_code,), 
            one=True
        )
        
        if not dept_row:
            return jsonify({"code": 1, "msg": "科室代码无效"})
            
        id_created_dept = dept_row['id_department']
        id_created_hosp = dept_row['id_hospital']
        created_dept_name = dept_row['department_name']

        # 3. 工单号生成
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        rand_code = str(random.randint(0, 99)).zfill(2)
        work_id = f"{timestamp}-{dept_code}-{rand_code}"

        # 4. 保存图片 (物理文件操作，需在事务前完成)
        # --- 首次发起保存报修图片 ---
        files = request.files.getlist('photos[]')
        # 调用工具函数，存入 report 文件夹
        report_photos_str = save_upload_photos(files, work_id, "report", REPORT_FOLDER)

        # 5. AI 识别
        ai_suggestion = get_ai_suggestion(demand, str(id_created_hosp))

        # 6. 获取受理科室及任务名称 (只读操作)
        work_department_name = None
        work_dept_id = ai_suggestion.get("work_department")
        if work_dept_id:
            w_dept_row = query_db("SELECT department_name FROM department WHERE id_department=?", (work_dept_id,), one=True)
            if w_dept_row:
                work_department_name = w_dept_row['department_name']

        task_name = "未知"
        task_id = ai_suggestion.get("task_type_id")
        if task_id:
            task_row = query_db("SELECT task_name FROM task_type WHERE id=?", (task_id,), one=True)
            if task_row:
                task_name = task_row['task_name']
        ai_location = ai_suggestion.get("extracted_location", "现场")
        work_type = ai_suggestion.get("work_type", "其它")
        # =========================================================
        # 核心：准备事务操作列表
        # =========================================================
        operations = []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_status = 0 # 已发起

        # SQL 1: 写入工单主表
        insert_order_sql = """
            INSERT INTO work_orders (
                id, source, demand, location, contact_phone, report_photo,
                created_at, status, task_type, work_type, 
                work_department, work_department_name,
                created_department_name, id_created_department, id_created_hospital
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        insert_order_args = (
            work_id, "人工发起", demand, ai_location, contact_phone, report_photos_str,
            now_str, current_status, task_id, work_type,
            work_dept_id, work_department_name,
            created_dept_name, id_created_dept, id_created_hosp
        )
        operations.append((insert_order_sql, insert_order_args))

        # SQL 2: 写入流转日志 (此处直接构造SQL，以便纳入同一事务)
        log_details = (
            f"【{created_dept_name}】发起工单,需求【{demand}】。AI识别结果:受理部门【{work_department_name or '未识别'}】，"
            f"工作类型【{work_type}】，任务类型【{task_name}】。"
        )
        insert_log_sql = """
            INSERT INTO work_order_logs 
            (work_id, operator_name, action, prev_status, curr_status, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        insert_log_args = (
            work_id, contact_phone, "首次发起（人工）", 99, current_status, log_details, now_str
        )
        operations.append((insert_log_sql, insert_log_args))

        # =========================================================
        # 执行事务
        # =========================================================
        success, error_msg = execute_transaction(operations)

        if success:
            return jsonify({
                "code": 0,
                "msg": "报单成功",
                "id": work_id,
                "task_name": task_name,
                "work_department": work_department_name,
                "work_type": work_type,
                "ai_location": ai_location  # 返回给前端展示
            })
        else:
            # 如果数据库写入失败，虽然文件已存，但数据库没有记录，保持了数据一致性
            print(f"Transaction Failed: {error_msg}")
            return jsonify({"code": 1, "msg": f"数据库写入失败: {error_msg}"})

    except Exception as e:
        print(f"Submit report error: {e}")
        return jsonify({"code": 1, "msg": "服务器内部错误，请稍后再试"})
    
# ---------------------------
# url获取医院 + 科室信息
# ---------------------------
@bp_orders.route('/url_get_deptname/<code>', methods=['GET'])
def get_info(code):
    try:
        if not code.isdigit() or len(code) != 7:
            return jsonify({"code": 1, "msg": "编码格式不合法"})

        hospital_code = code[:3]
        
        sql = """
            SELECT h.hospital_name, d.department_name
            FROM hospital h
            LEFT JOIN department d ON h.id_hospital = d.id_hospital AND d.department_url = ?
            WHERE h.id_hospital = ?
        """
        
        # 使用 query_db 查询，one=True 表示获取单条结果
        row = query_db(sql, (code, hospital_code), one=True)
        print(row)
        # 检查结果是否存在以及字段是否有值
        # 注意：如果 query_db 返回的是字典(dict_factory)，请使用 row['hospital_name']
        # 这里假设返回的是元组或支持下标访问的 Row 对象，与原代码逻辑保持一致
        if row and row['hospital_name'] and row['department_name']:
            return jsonify({
                "code": 0,
                "hospital_name": row['hospital_name'],
                "department_name": row['department_name']
            })

        return jsonify({"code": 1, "msg": "未找到对应医院或科室信息"})

    except Exception as e:
        print(f"Error in get_info: {e}")
        return jsonify({"code": 1, "msg": "查询失败"})

# ---------------------------
# 查询“我的科室”在“目标科室”的未完成工单
# ---------------------------
@bp_orders.route('/get_incomplete_orders/<code>', methods=['GET'])
@login_required
def get_incomplete_orders(code):
    user = get_current_user_info()
    my_dept_id = user.get('id_department')

    # 1. 解析扫码得到的科室 (发起科室)
    # 假设 code 是 department_url
    target_dept = query_db("SELECT id_department, department_name FROM department WHERE department_url = ?", (code,), one=True)
    
    if not target_dept:
        return "无效的科室代码", 404

    target_dept_id = target_dept['id_department']
    target_dept_name = target_dept['department_name']

    # 2. 查询工单
    # 条件：
    #   - work_department = 我当前所属的维修科室
    #   - id_created_department = 扫码所在的科室
    #   - status < 4 (未完成状态：0待派, 1已派, 2维修中, 3挂起)
    #   或者根据你的需求，status IN (0, 1, 2, 3)
    
    sql = """
            SELECT * FROM work_orders 
            WHERE work_department = ? 
            AND id_created_department = ? 
            AND status IN (0, 1, 2, 11, 12)
            AND (with_device IS NULL OR with_device = '')
            ORDER BY created_at DESC
                """
    
    orders = query_db(sql, (my_dept_id, target_dept_id))
    return render_template(
        "orders/mobile_incomplete.html", 
        orders=orders,
        target_dept_name=target_dept_name
    )

# ---------------------------
# 查询“目标科室”的所有未完成工单
# ---------------------------
@bp_orders.route('/get_dept_incomplete_orders/<code>', methods=['GET'])
def get_dept_incomplete_orders(code):
    # 1. 解析扫码得到的科室 (发起科室)
    # 假设 code 是 department_url
    target_dept = query_db("SELECT id_department, department_name FROM department WHERE department_url = ?", (code,), one=True)
    
    if not target_dept:
        return "无效的科室代码", 404

    target_dept_id = target_dept['id_department']
    target_dept_name = target_dept['department_name']

    # 2. 查询工单
    # 条件：
    #   - work_department = 我当前所属的维修科室
    #   - id_created_department = 扫码所在的科室
    #   - status < 4 (未完成状态：0待派, 1已派, 2维修中, 3挂起)
    #   或者根据你的需求，status IN (0, 1, 2, 3)
    
    sql = """
        SELECT * FROM work_orders 
        WHERE id_created_department = ? 
          AND status IN (0, 1, 2, 3)
        ORDER BY created_at DESC
    """
    
    orders = query_db(sql, (target_dept_id,))
    return render_template(
        "orders/mobile_dept_incomplete.html", 
        orders=orders,
        target_dept_name=target_dept_name
    )


# ---------------------------
# 工作人员人员到达现场签到接口
# ---------------------------
@bp_orders.route('/api/work_order/arrive/<code>', methods=['POST'])

def arrive(code):
    # 1. 如果是 POST 请求，且 code 参数可能在 form data 里 (适配你提供的 JS $.post)
    work_id = code
    if request.method == 'POST':
        work_id = request.form.get('work_id', code)
    
    try:
        # 2. 获取当前操作人信息
        user = get_current_user_info()
        operator_name = user.get('username', '工作人员')

        # 3. 查询工单当前状态
        # 确保工单存在，且状态处于未完成阶段 (例如 0:待派, 1:已派/待维修)
        # 假设状态 2 代表 "维修中/已到达"
        sql = "SELECT status, work_department FROM work_orders WHERE id = ?"
        order = query_db(sql, (work_id,), one=True)
        
        if not order:
            return jsonify({"code": 1, "msg": "工单不存在或参数错误"})

        current_status = int(order['status'])
        
        # 4. 状态校验 (防止重复签到)
        if current_status != 1:
            return jsonify({"code": 1, "msg": "该工单已签到或已完成，无需重复操作"})

        # 5. 更新数据库状态 -> 2 (维修中/已到达)
        update_sql = "UPDATE work_orders SET status = 2 WHERE id = ?"
        success, res = modify_db(update_sql, (work_id,))

        if success:
            # 6. 记录流转日志
            record_order_flow(
                work_id=work_id,
                action="工作人员到达现场",
                operator=f"{operator_name}",
                prev_status=current_status,
                curr_status=2,
                details=f"工作人员【{operator_name}】到达现场签到，开始工作"
            )
            return jsonify({"code": 0, "msg": "签到成功"})
        else:
            return jsonify({"code": 1, "msg": "系统繁忙，签到失败"})

    except Exception as e:
        print(f"Arrive error: {e}")
        return jsonify({"code": 1, "msg": "服务器内部错误"})
    

# ---------------------------
# 工作人员挂起工单接口
# ---------------------------
@bp_orders.route('/api/work_order/suspend', methods=['POST'])

def suspend_order():
    # 1. 获取前端传递的参数
    work_id = request.form.get('work_id')
    reason = request.form.get('reason')

    if not work_id or not reason:
        return jsonify({"code": 1, "msg": "参数缺失：工单ID或挂起原因不能为空"})
    
    try:
        # 2. 获取当前操作人信息
        user = get_current_user_info()
        operator_name = user.get('username', '工作人员')

        # 3. 查询工单当前状态
        sql = "SELECT status FROM work_orders WHERE id = ?"
        order = query_db(sql, (work_id,), one=True)
        
        if not order:
            return jsonify({"code": 1, "msg": "工单不存在"})

        current_status = int(order['status'])
        # 4. 状态校验
        if current_status  in [3,4,5,6]:  
            return jsonify({"code": 1, "msg": "当前工单状态无法挂起（可能已完成）"})
        if current_status == 12:
            return jsonify({"code": 1, "msg": "委外处理中，请勿派单"})
        if current_status == 13:
            return jsonify({"code": 1, "msg": "本工单已驳回，请勿派单"})       

        # 5. 更新数据库状态 -> 11 (11代表 "挂起/暂停" 状态)
        update_sql = "UPDATE work_orders SET status = 11 WHERE id = ?"
        success, res = modify_db(update_sql, (work_id,))

        if success:
            # 6. 记录流转日志
            # 将具体的挂起原因记录在 details 字段中
            record_order_flow(
                work_id=work_id,
                action="工单挂起",
                operator=f"{operator_name}",
                prev_status=current_status,
                curr_status=11,  # 这里的 5 需与上面 update_sql 保持一致
                details=f"{operator_name}挂起工单，原因：{reason}"
            )
            return jsonify({"code": 0, "msg": "工单已挂起"})
        else:
            return jsonify({"code": 1, "msg": "系统繁忙，挂起失败"})

    except Exception as e:
        print(f"Suspend error: {e}")
        return jsonify({"code": 1, "msg": "服务器内部错误"})
    



# 1. 渲染完工填报页面的路由
@bp_orders.route('/work_order/finish_form')
def finish_form_view():
    return render_template('orders/finish_form.html')


# 2. 处理完工提交的 API 接口
@bp_orders.route('/api/work_order/finish_submit', methods=['POST'])
def finish_submit_api():
    try:
        work_id = request.form.get('work_id')
        summary = request.form.get('summary')

        if not work_id or not summary:
            return jsonify({"code": 1, "msg": "参数缺失"})

        # 获取用户信息
        user = get_current_user_info()
        operator_name = user.get('username', '工作人员')

        # 1. 处理图片上传
        files = request.files.getlist('photos[]')
        finish_photos_str = save_upload_photos(
            files, work_id, "finish", FINISH_FOLDER
        )

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 2. 构建事务操作列表
        operations = []

        # 2.1 更新工单状态
        update_sql = """
            UPDATE work_orders
            SET status = ?,
                work_content = ?,
                finish_photo = ?
            WHERE id = ?
        """
        operations.append((
            update_sql,
            (3, summary, finish_photos_str,  work_id)
        ))

        # 2.2 写入工单流转日志
        log_sql = """
            INSERT INTO work_order_logs
            (work_id, action, operator_name, prev_status, curr_status, details, staff, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        operations.append((
            log_sql,
            (
                work_id,
                "完成工单（二维码）",
                operator_name,
                2,              # prev_status
                3,              # curr_status
                f"工作人员完成工单，本次工作内容：{summary}",
                None,
                current_time
            )
        ))

        # 3. 执行事务
        success, err = execute_transaction(operations)

        if success:
            return jsonify({"code": 0, "msg": "完工成功"})
        else:
            return jsonify({"code": 1, "msg": f"提交失败：{err}"})

    except Exception as e:
        print(f"Finish Submit Error: {e}")
        return jsonify({"code": 1, "msg": "服务器内部错误"})
