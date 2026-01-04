# models.py
from apps.tools.extensions import db  # 假设你已经把 db = SQLAlchemy() 放在了 extensions.py
from datetime import datetime

# ==========================================
# 组织架构 (Hospital, Department, User)
# ==========================================

class Hospital(db.Model):
    __tablename__ = 'hospital'
    id_hospital = db.Column(db.Integer, primary_key=True, autoincrement=True)
    area_name = db.Column(db.String(255))
    hospital_name = db.Column(db.String(255))

    # 关系: 一个医院有多个科室
    departments = db.relationship('Department', backref='hospital', lazy='dynamic')

class Department(db.Model):
    __tablename__ = 'department'
    id_department = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # 外键关联
    id_hospital = db.Column(db.Integer, db.ForeignKey('hospital.id_hospital'))
    
    department_url = db.Column(db.String(255), unique=True)
    work_flag = db.Column(db.Integer, default=1) # 1=启用
    department_name = db.Column(db.String(255))
    id_department_in_hospital = db.Column(db.Integer)
    description = db.Column(db.Text)

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50))
    id_hospital = db.Column(db.String(50))   # 注意：原表定义为 TEXT
    id_department = db.Column(db.String(50)) # 注意：原表定义为 TEXT
    staff_flag = db.Column(db.Integer)       # 0 or 1
    user_devices_id = db.Column(db.Text)

# ==========================================
# 资产设备 (Facility, Device Events)
# ==========================================

class FacilityObject(db.Model):
    __tablename__ = 'facility_object'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    parent_id = db.Column(db.Integer, default=0)
    name = db.Column(db.String(255), nullable=False)
    model = db.Column(db.String(255))
    
    # 归属与位置
    id_hospital = db.Column(db.Integer)
    hospital_name = db.Column(db.String(255))
    id_department = db.Column(db.Integer)        # 管理科室
    department_name = db.Column(db.String(255))
    use_department_id = db.Column(db.Integer)    # 使用科室
    use_department_name = db.Column(db.String(255))
    
    ancestor_path = db.Column(db.Text, default='0')
    install_location = db.Column(db.String(255))
    status = db.Column(db.Integer, default=1)
    extra_json = db.Column(db.Text)
    category = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class DeviceEvent(db.Model):
    __tablename__ = 'device_events'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.Integer, nullable=False, index=True) # 有索引
    event_type = db.Column(db.String(50))
    content = db.Column(db.Text)
    cycle_val = db.Column(db.Integer, default=0)
    cycle_unit = db.Column(db.String(20))
    next_run_time = db.Column(db.DateTime)
    creator_id = db.Column(db.Integer)
    id_hospital = db.Column(db.Integer)
    hospital_name = db.Column(db.String(100))
    id_department = db.Column(db.Integer)
    department_name = db.Column(db.String(100))

class DeviceLog(db.Model):
    __tablename__ = 'devices_log'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.Integer, nullable=False)
    occur_time = db.Column(db.DateTime, nullable=False)
    hospital_name = db.Column(db.Text, nullable=False)
    hospital_id = db.Column(db.Integer, nullable=False)
    start_department_name = db.Column(db.Text, nullable=False)
    start_department_id = db.Column(db.Integer, nullable=False)
    handle_department_name = db.Column(db.Text, nullable=False)
    handle_department_id = db.Column(db.Integer, nullable=False)
    related_work_order = db.Column(db.Text)
    work_content = db.Column(db.Text)
    staff = db.Column(db.Text)
    type = db.Column(db.Text)

# ==========================================
# 工单系统 (WorkOrder, Logs, Message)
# ==========================================

class WorkOrder(db.Model):
    __tablename__ = 'work_orders'
    id = db.Column(db.String(50), primary_key=True, unique=True) # ID是文本
    source = db.Column(db.String(50))
    
    # 关联
    work_department = db.Column(db.Integer, db.ForeignKey('department.id_department'))
    work_department_rel = db.relationship('Department', foreign_keys=[work_department])

    demand = db.Column(db.Text)
    work_type = db.Column(db.String(50))
    location = db.Column(db.String(255))
    task_type = db.Column(db.String(50))
    contact_phone = db.Column(db.String(50))
    report_photo = db.Column(db.Text)
    staff = db.Column(db.Text)
    work_content = db.Column(db.Text)
    finish_photo = db.Column(db.Text)
    is_rework = db.Column(db.Integer, default=0)
    with_device = db.Column(db.Integer)
    feedback = db.Column(db.Text)
    evaluate_score = db.Column(db.Integer)
    remark = db.Column(db.Text)
    status = db.Column(db.String(20)) # 原表是 TEXT
    
    work_department_name = db.Column(db.String(255))
    created_department_name = db.Column(db.String(255))
    id_created_hospital = db.Column(db.Integer)
    id_created_department = db.Column(db.Integer)
    created_at = db.Column(db.String(50)) # SQLite存的是字符串时间
    
    outsource_flag = db.Column(db.Integer)
    task_score = db.Column(db.Integer)
    task_coefficient = db.Column(db.Integer)
    arrival_score = db.Column(db.Integer)
    repair_score = db.Column(db.Integer)
    total_score = db.Column(db.Integer)
    final_score = db.Column(db.Integer)

class WorkOrderLog(db.Model):
    __tablename__ = 'work_order_logs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    work_id = db.Column(db.String(50), nullable=False)
    operator_name = db.Column(db.String(50))
    action = db.Column(db.String(50), nullable=False)
    prev_status = db.Column(db.Integer)
    curr_status = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.String(50))
    staff = db.Column(db.Text)

class DelWorkOrder(db.Model):
    __tablename__ = 'del_workorders'
    id = db.Column(db.String(50), primary_key=True)
    delete_reason = db.Column(db.Text)
    deleted_at = db.Column(db.String(50))
    # ... 其他字段省略或根据需要按需添加，因为是备份表通常不需要ORM操作 ...
    demand = db.Column(db.Text)
    work_type = db.Column(db.String(50))
    location = db.Column(db.String(255))
    task_type = db.Column(db.String(50))
    contact_phone = db.Column(db.String(50))
    report_photo = db.Column(db.Text)
    staff = db.Column(db.Text)
    work_content = db.Column(db.Text)
    finish_photo = db.Column(db.Text)
    is_rework = db.Column(db.Integer, default=0)
    with_device = db.Column(db.Integer)
    feedback = db.Column(db.Text)
    evaluate_score = db.Column(db.Integer)
    remark = db.Column(db.Text)
    status = db.Column(db.String(20)) # 原表是 TEXT
    
    work_department_name = db.Column(db.String(255))
    created_department_name = db.Column(db.String(255))
    id_created_hospital = db.Column(db.Integer)
    id_created_department = db.Column(db.Integer)
    created_at = db.Column(db.String(50)) # SQLite存的是字符串时间
    
    outsource_flag = db.Column(db.Integer)
    task_score = db.Column(db.Integer)
    task_coefficient = db.Column(db.Integer)
    arrival_score = db.Column(db.Integer)
    repair_score = db.Column(db.Integer)
    total_score = db.Column(db.Integer)
    final_score = db.Column(db.Integer)

class MessageQueue(db.Model):
    __tablename__ = 'message_queue'
    id_message = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_workorders = db.Column(db.String(50), db.ForeignKey('work_orders.id'))
    message_type = db.Column(db.String(50))
    send_wx = db.Column(db.Integer, default=0)

class TaskType(db.Model):
    __tablename__ = 'task_type'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_name = db.Column(db.String(100))
    description = db.Column(db.Text)
    score = db.Column(db.Integer)
    baseline_time = db.Column(db.Integer)
    key_word = db.Column(db.String(255))

# ==========================================
# 物资管理 (Materials)
# ==========================================

class MaterialStock(db.Model):
    __tablename__ = 'material_stock'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    model = db.Column(db.String(255))
    spec = db.Column(db.String(255))
    quantity = db.Column(db.Integer, default=0)
    unit = db.Column(db.String(50))
    price = db.Column(db.Numeric(10, 2), default=0)
    remark = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    id_hospital = db.Column(db.String(50))
    hospital_name = db.Column(db.String(255))

class MaterialLog(db.Model):
    __tablename__ = 'material_logs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    material_name = db.Column(db.String(255))
    model = db.Column(db.String(255))
    spec = db.Column(db.String(255))
    change_qty = db.Column(db.Integer)
    price = db.Column(db.Numeric(10, 2))
    total_cost = db.Column(db.Numeric(10, 2))
    action_type = db.Column(db.String(50))
    work_order_id = db.Column(db.String(50))
    operator = db.Column(db.String(50))
    remark = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    hospital_name = db.Column(db.String(255))
    id_hospital = db.Column(db.String(50))
    id_use_department = db.Column(db.Integer) # 上次讨论中新增的字段

class MaterialRequest(db.Model):
    __tablename__ = 'material_requests'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    material_name = db.Column(db.String(255), nullable=False)
    model = db.Column(db.String(255))
    spec = db.Column(db.String(255))
    apply_qty = db.Column(db.Integer, nullable=False)
    unit = db.Column(db.String(50))
    estimated_price = db.Column(db.Numeric(10, 2))
    dept_name = db.Column(db.String(255))
    applicant = db.Column(db.String(50))
    reason = db.Column(db.Text)
    remark = db.Column(db.Text)
    status = db.Column(db.Integer, default=0)
    approver = db.Column(db.String(50))
    approval_time = db.Column(db.DateTime)
    reject_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    id_hospital = db.Column(db.String(50))
    # Field18 和 id_department 类型需要确认，这里按原表结构
    Field18 = db.Column(db.Integer) 
    id_department = db.Column(db.Text)
    user_id = db.Column(db.Text)

# ==========================================
# 排班与考勤 (Shift, Roster, Calendar)
# ==========================================

class ShiftSetting(db.Model):
    __tablename__ = 'shift_settings'
    id = db.Column(db.Integer, primary_key=True, unique=True, nullable=False)
    id_department = db.Column(db.Text, nullable=False)
    name = db.Column(db.Text, nullable=False)
    color = db.Column(db.Text, default='#1E9FFF')
    start_time = db.Column(db.Text, nullable=False)
    end_time = db.Column(db.Text, nullable=False)
    is_next_day = db.Column(db.Integer, default=0)
    workday_mode = db.Column(db.Text, default='NONE')
    weekend_mode = db.Column(db.Text, default='NONE')
    duty_count = db.Column(db.Integer, default=1)
    fixed_user_ids = db.Column(db.Text)
    exclude_user_ids = db.Column(db.Text)

class ScheduleRotation(db.Model):
    __tablename__ = 'schedule_rotation'
    # 复合主键
    dept_id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.Integer)

class Roster(db.Model):
    __tablename__ = 'roster'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    roster_date = db.Column(db.String(50), nullable=False)
    shift_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer)
    department_id = db.Column(db.Integer)

class CalendarException(db.Model):
    __tablename__ = 'calendar_exception'
    # 联合唯一索引在 __table_args__ 中定义
    __table_args__ = (
        db.UniqueConstraint('dept_id', 'exception_date', name='uniq_dept_date'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dept_id = db.Column(db.String(50))
    exception_date = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(20), nullable=False) # HOLIDAY, WORKDAY
    note = db.Column(db.Text)

# ==========================================
# 外包管理 (Outsourcing)
# ==========================================

class OutsourcingUnit(db.Model):
    __tablename__ = 'outsourcing_units'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    unit_name = db.Column(db.String(255), nullable=False)
    unit_desc = db.Column(db.Text)
    id_department = db.Column(db.Integer)
    department_name = db.Column(db.String(255))
    id_hospital = db.Column(db.Integer, nullable=False)
    hospital_name = db.Column(db.String(255))
    status = db.Column(db.Integer, default=1)

class OutsourcingRecord(db.Model):
    __tablename__ = 'outsourcing_records'

    # --- 基础 ID 信息 ---
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    work_order_id = db.Column(db.String(50), nullable=False) 
    outsourcing_unit_id = db.Column(db.Integer, nullable=False)
    unit_name = db.Column(db.String(255))
    
    # 外包单位所属/指派部门
    outsourcing_unit_by_dept_id = db.Column(db.Integer, nullable=False)
    outsourcing_unit_by_dept_name = db.Column(db.String(255))

    # --- 时间流转 ---
    assigned_at = db.Column(db.DateTime, default=datetime.now) # 派单时间
    vendor_arrive_at = db.Column(db.String(50))                # 维修人员到达时间 (SQL原表是TEXT)
    vendor_finished_at = db.Column(db.DateTime)                # 维修完成时间

    # --- 任务详情 ---
    work_content = db.Column(db.Text)
    demand = db.Column(db.Text)            # 补充字段：需求描述
    location = db.Column(db.String(255))   # 补充字段：地点
    contact_phone = db.Column(db.String(50)) # 补充字段：联系电话
    
    # --- 金额相关 ---
    quoted_amount = db.Column(db.Numeric(10, 2), default=0) # 报价
    final_amount = db.Column(db.Numeric(10, 2), default=0)  # 最终金额
    final_amount_reason = db.Column(db.Integer)             # 补充字段：改价原因 (SQL定义为Integer，可能是枚举值)
    cherck_amount_user = db.Column(db.String(255))          # 补充字段：核价人 (注意保留SQL中的拼写 cherck)

    # --- 评价与状态 ---
    status = db.Column(db.Integer, default=0)
    evaluation_comment = db.Column(db.Text)
    manager_evaluation = db.Column(db.Text) # 补充字段：管理科室评价
    remark = db.Column(db.Text)

    # --- 图片证据 (SQL类型为TEXT，通常存路径) ---
    finish_photo = db.Column(db.Text)   # 补充字段：完工照片
    manager_photo = db.Column(db.Text)  # 补充字段：管理员上传的照片

    # --- 相关人员与部门 ---
    use_department_id = db.Column(db.Integer)
    use_department_name = db.Column(db.String(255))
    use_department_username = db.Column(db.String(255))     # 补充字段：使用科室确认人
    manager_department_username = db.Column(db.String(255)) # 补充字段：管理科室确认人