from flask import render_template, request, jsonify
from apps.tools.extensions import db  # 引入 SQLAlchemy 实例
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices
import datetime
import time
import random
# 引入你的模型类 (请确保路径正确)
from apps.tools.models import FacilityObject, WorkOrder, WorkOrderLog, DeviceLog, TaskType, Hospital


class OrderStatus:
    PENDING = '0'      # 待派单
    DISPATCHED = '1'   # 已派单
    COMPLETED = '5'    # 已完成/已结单

# ---------------------------------------------------------------------
# 1. 巡检打卡页面 (渲染)
# ---------------------------------------------------------------------
@bp_devices.route('/check_in/<int:device_id>')
def check_in_page(device_id):
    # 1. 获取设备信息 (ORM 查询)
    # FacilityObject 模型里已经存了 hospital_name，所以不需要联表查 Hospital
    # 如果需要联表，可以使用 db.session.query(FacilityObject, Hospital).join...
    device = FacilityObject.query.get(device_id)
    
    if not device:
        return "设备不存在或已被移除", 404

    # 2. 获取当前用户信息
    user = get_current_user_info()
    
    # 3. 判定访问状态
    access_status = 'guest'
    unauthorized_msg = ""

    if user:
        # 注意：ORM 对象属性访问用 .id_hospital，字典用 ['id_hospital']
        # 这里 user 是字典 (get_current_user_info返回的)，device 是对象
        if str(user.get('id_hospital')) == str(device.id_hospital):
            access_status = 'allowed'
        else:
            access_status = 'denied'
            unauthorized_msg = f"当前账号归属【{user.get('hospital_name')}】，无法查看【{device.hospital_name}】的维保记录。"

    # 4. 根据状态获取数据
    pending_orders = []
    recent_logs = []

    if access_status == 'allowed':
        # 1. 先查询出 ORM 对象列表
        orders_objects = WorkOrder.query.filter(
            WorkOrder.with_device == device_id,
            WorkOrder.status.in_([OrderStatus.PENDING, OrderStatus.DISPATCHED])
        ).order_by(WorkOrder.created_at.desc()).all()

        # 2. 【核心修改】将对象列表转换为字典列表
        # 只有转成字典，前端的 {{ orders | tojson }} 才不会报错
        pending_orders = []
        for order in orders_objects:
            pending_orders.append({
                "id": order.id,
                "demand": order.demand,
                "status": order.status,
                "work_type": order.work_type,
                # 注意：如果 created_at 是 datetime 对象，必须转成字符串，否则 JSON 也会报错
                "created_at": str(order.created_at) if order.created_at else "" 
            })

        # 查询最近日志 (ORM 对象直接传给模板循环显示没问题，但如果日志也要 tojson，也得转字典)
        recent_logs = DeviceLog.query.filter_by(device_id=device_id)\
            .order_by(DeviceLog.occur_time.desc()).limit(10).all()

    return render_template(
        'devices/devices_check_in.html',
        device=device,
        orders=pending_orders,
        logs=recent_logs,
        user=user,
        access_status=access_status,
        unauthorized_msg=unauthorized_msg
    )

# ---------------------------------------------------------------------
# 2. 巡检签到 API (执行动作)
# ---------------------------------------------------------------------
@bp_devices.route('/api/orders_check_in', methods=['POST'])
def api_orders_check_in():
    user = get_current_user_info()
    if not user:
        return jsonify({"code": 401, "msg": "身份信息已过期，请重新登录"})

    data = request.json or {}
    order_id = data.get('order_id')
    if not order_id:
        return jsonify({"code": 1, "msg": "参数错误：缺少工单ID"})

    # 1. 查询工单 (ORM)
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({"code": 1, "msg": "未找到相关工单记录"})
    
    # 获取关联的设备信息 (用于鉴权和记录日志)
    # 假设 WorkOrder 模型没有直接关联 FacilityObject，我们手动查一下
    # 如果你在 WorkOrder 里定义了 device = relationship(...)，则可以直接用 order.device
    device_obj = FacilityObject.query.get(order.with_device)
    if not device_obj:
         return jsonify({"code": 1, "msg": "关联设备数据异常"})

    # 2. 越权校验
    if str(user['id_hospital']) != str(device_obj.id_hospital):
        return jsonify({"code": 403, "msg": "越权操作：您无法处理非本院工单"})

    if str(order.status) == OrderStatus.COMPLETED:
        return jsonify({"code": 1, "msg": "该工单已处于完成状态"})

    # 3. 准备数据
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_dt = datetime.datetime.now() #用于 DateTime 类型字段
    username = user['username']
    
    # 获取任务类型名称和分数
    task_name = "日常巡检"
    task_score = 0
    
    # 查找任务类型 (假设 order.task_type 存的是 ID)
    if order.task_type:
        # 注意 task_type 可能是字符串或数字，根据你的模型调整
        task_type_obj = TaskType.query.get(int(order.task_type)) 
        if task_type_obj:
            task_name = task_type_obj.task_name
            task_score = task_type_obj.score or 0
    
    # 优先使用工单自带的分数 (如果有)
    current_score = order.task_score if order.task_score else task_score

    # 4. 执行事务 (ORM)
    try:
        # A. 更新工单状态
        work_content = f"工作人员【{username}】到达【{device_obj.name}】现场，完成了本【{task_name}】工单"
        
        order.status = OrderStatus.COMPLETED
        order.staff = username
        order.work_content = work_content
        order.task_score = current_score
        order.total_score = current_score
        order.repair_score = 0
        order.arrival_score = 0
        order.task_coefficient = 0
        order.outsource_flag = 0
        order.remark = ''
        order.feedback = ''
        
        # B. 记录工单轨迹日志
        log_detail = f"工作人员【{username}】到达【{device_obj.name}】现场，完成了本次【{task_name}】类工单，本次工单赋【{current_score}】分"
        
        flow_log = WorkOrderLog(
            work_id=order_id,
            action='完成工单（设备）',
            operator_name=username,
            prev_status=int(OrderStatus.PENDING), # 假设之前是待处理，严谨点可以用 old_status 变量
            curr_status=int(OrderStatus.COMPLETED),
            staff=username,
            details=log_detail,
            created_at=now_str
        )
        db.session.add(flow_log)

        # C. 写入设备日志
        dev_log = DeviceLog(
            device_id=order.with_device,
            occur_time=now_dt, # 注意：模型如果是 DateTime 类型，这里传 datetime 对象
            hospital_name=user['hospital_name'],
            hospital_id=user['id_hospital'],
            start_department_name=order.created_department_name,
            start_department_id=order.id_created_department,
            handle_department_name=user['department_name'],
            handle_department_id=user['id_department'],
            work_content=f"【{task_name}签到】：工作人员【{username}】完成{task_name}工单（工单号：{order_id}）",
            staff=username,
            type=task_name,
            related_work_order=order_id
        )
        db.session.add(dev_log)

        # 提交事务
        db.session.commit()
        return jsonify({"code": 0, "msg": "签到成功"})

    except Exception as e:
        db.session.rollback()
        print(f"Checkin Transaction Error: {e}")
        return jsonify({"code": 500, "msg": f"数据库写入失败: {str(e)}"})
    
# ---------------------------------------------------------------------
# 3. 故障上报页面 (弹窗 Iframe)
# ---------------------------------------------------------------------
@bp_devices.route('/report_fault_page')
def report_fault_page():
    device_id = request.args.get('device_id')
    if not device_id:
        return "参数错误", 400
    
    # ORM 查询
    device = FacilityObject.query.get(device_id)
    return render_template('devices/devices_report_form.html', device=device)

# ---------------------------------------------------------------------
# 4. 故障上报提交 API
# ---------------------------------------------------------------------
@bp_devices.route('/api/report_fault', methods=['POST'])
def api_report_fault():
    # 1. 接收参数
    data = request.form
    device_id = data.get('device_id')
    demand = data.get('demand', '用户未填写详情')
    location = data.get('location', '')
    contact_phone = data.get('contact_phone', '')
    
    user = get_current_user_info()
    
    # 2. 查询设备
    device = FacilityObject.query.get(device_id)
    if not device:
        return jsonify({"code": 1, "msg": "设备不存在"})

    # 3. 生成数据
    order_id = f"R{int(time.time())}{random.randint(100,999)}" 
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    creator_name = user['username'] if user else "扫码报修用户"
    creator_id = str(user['id']) if user else "0"

    try:
        # 4. 创建工单对象
        new_order = WorkOrder(
            id=order_id,
            work_type='故障报修',
            demand=demand,
            location=location,
            contact_phone=contact_phone,
            status=OrderStatus.PENDING,
            
            with_device=device.id,
            id_created_hospital=device.id_hospital,     
            id_created_department=device.use_department_id,
            created_department_name=device.use_department_name,
            work_department=device.id_department,
            work_department_name=device.department_name,
            created_at=now_str
        )
        
        # 注意：如果你的 WorkOrder 模型确实没有 creator_id，
        # 你可能需要把这两个字段加到 remark 里或者修改模型
        if not hasattr(new_order, 'creator_name'):
             new_order.remark = f"报修人:{creator_name}, ID:{creator_id}"

        db.session.add(new_order)

        # 5. 创建日志对象
        log_details = f"故障上报。报修内容：{demand}"
        new_log = WorkOrderLog(
            work_id=order_id,
            action='工单创建',
            operator_name=creator_name,
            details=log_details,
            created_at=now_str,
            # type 字段在你之前的 models.py 里没有定义？
            # 如果 Log 表有 type 列，请确保 models.py 里有 type = db.Column(...)
            # 暂时注释掉或者通过 details 体现
            # type='start' 
        )
        # 临时处理：如果你的 WorkOrderLog 模型没有 type 字段，但你想存，
        # 必须先去修改 models.py 添加 type 字段。
        # 假设你已经加了：
        if hasattr(new_log, 'type'):
             new_log.type = 'start'

        db.session.add(new_log)

        # 6. 提交事务
        db.session.commit()
        
        return jsonify({"code": 0, "msg": "上报成功", "order_id": order_id})

    except Exception as e:
        db.session.rollback()
        print(f"Report Fault Error: {e}")
        return jsonify({"code": 1, "msg": f"系统繁忙，上报失败: {str(e)}"})