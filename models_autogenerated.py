# coding: utf-8
from apps.tools.extensions import db



class CalendarException(db.Model):
    __tablename__ = 'calendar_exception'

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Text)
    exception_date = db.Column(db.Text)
    type = db.Column(db.Text)
    note = db.Column(db.Text)


class DelWorkorders(db.Model):
    __tablename__ = 'del_workorders'

    id = db.Column(db.Text, primary_key=True)
    delete_reason = db.Column(db.Text)
    deleted_at = db.Column(db.Text)
    source = db.Column(db.Text)
    work_department = db.Column(db.Text)
    demand = db.Column(db.Text)
    created_at = db.Column(db.Text)
    work_type = db.Column(db.Text)
    location = db.Column(db.Text)
    task_type = db.Column(db.Text)
    contact_phone = db.Column(db.Text)
    report_photo = db.Column(db.Text)
    dispatched_at = db.Column(db.Text)
    dispatched_duration = db.Column(db.Integer)
    staff = db.Column(db.Text)
    arrived_at = db.Column(db.Text)
    arrive_duration = db.Column(db.Integer)
    suspend_at = db.Column(db.Text)
    suspend_reason = db.Column(db.Text)
    suspend_duration = db.Column(db.Integer)
    finished_at = db.Column(db.Text)
    work_content = db.Column(db.Text)
    repair_duration = db.Column(db.Integer)
    finish_photo = db.Column(db.Text)
    arrive_point = db.Column(db.Integer)
    finish_point = db.Column(db.Integer)
    task_demand_point = db.Column(db.Integer)
    task_x = db.Column(db.Float)
    info_completed_at = db.Column(db.Text)
    is_rework = db.Column(db.Integer)
    with_device_sys = db.Column(db.Integer)
    with_device = db.Column(db.Integer)
    feedback = db.Column(db.Text)
    evaluate_score = db.Column(db.Integer)
    final_point = db.Column(db.Float)
    remark = db.Column(db.Text)


class Department(db.Model):
    __tablename__ = 'department'

    id_department = db.Column(db.Integer, primary_key=True)
    id_hospital = db.Column(db.Integer)
    department_url = db.Column(db.Text)
    work_flag = db.Column(db.Integer)
    department_name = db.Column(db.Text)
    id_department_in_hospital = db.Column(db.Integer)
    description = db.Column(db.Text)


class DeviceEvents(db.Model):
    __tablename__ = 'device_events'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer)
    event_type = db.Column(db.String(255))
    content = db.Column(db.Text)
    cycle_val = db.Column(db.Integer)
    cycle_unit = db.Column(db.String(255))
    next_run_time = db.Column(db.DateTime)
    creator_id = db.Column(db.Integer)
    id_hospital = db.Column(db.Integer)
    hospital_name = db.Column(db.String(255))
    id_department = db.Column(db.Integer)
    department_name = db.Column(db.String(255))


class DevicesLog(db.Model):
    __tablename__ = 'devices_log'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer)
    occur_time = db.Column(db.DateTime)
    hospital_name = db.Column(db.Text)
    hospital_id = db.Column(db.Integer)
    start_department_name = db.Column(db.Text)
    start_department_id = db.Column(db.Integer)
    handle_department_name = db.Column(db.Text)
    handle_department_id = db.Column(db.Integer)
    related_work_order = db.Column(db.Text)
    work_content = db.Column(db.Text)
    staff = db.Column(db.Text)
    type = db.Column(db.Text)


class FacilityObject(db.Model):
    __tablename__ = 'facility_object'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer)
    name = db.Column(db.Text)
    model = db.Column(db.Text)
    id_hospital = db.Column(db.Integer)
    hospital_name = db.Column(db.Text)
    id_department = db.Column(db.Integer)
    department_name = db.Column(db.Text)
    use_department_id = db.Column(db.Integer)
    use_department_name = db.Column(db.Text)
    ancestor_path = db.Column(db.Text)
    install_location = db.Column(db.Text)
    status = db.Column(db.Integer)
    extra_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    category = db.Column(db.Text)


class Hospital(db.Model):
    __tablename__ = 'hospital'

    id_hospital = db.Column(db.Integer, primary_key=True)
    area_name = db.Column(db.Text)
    hospital_name = db.Column(db.Text)


class MaterialLogs(db.Model):
    __tablename__ = 'material_logs'

    id = db.Column(db.Integer, primary_key=True)
    material_name = db.Column(db.Text)
    model = db.Column(db.Text)
    spec = db.Column(db.Text)
    change_qty = db.Column(db.Integer)
    price = db.Column(db.Numeric(10, 2))
    total_cost = db.Column(db.Numeric(10, 2))
    action_type = db.Column(db.Text)
    work_order_id = db.Column(db.Text)
    operator = db.Column(db.Text)
    remark = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    hospital_name = db.Column(db.Text)
    id_hospital = db.Column(db.Text)
    id_use_department = db.Column(db.Integer)


class MaterialRequests(db.Model):
    __tablename__ = 'material_requests'

    id = db.Column(db.Integer, primary_key=True)
    material_name = db.Column(db.Text)
    model = db.Column(db.Text)
    spec = db.Column(db.Text)
    apply_qty = db.Column(db.Integer)
    unit = db.Column(db.Text)
    estimated_price = db.Column(db.Numeric(10, 2))
    dept_name = db.Column(db.Text)
    applicant = db.Column(db.Text)
    reason = db.Column(db.Text)
    remark = db.Column(db.Text)
    status = db.Column(db.Integer)
    approver = db.Column(db.Text)
    approval_time = db.Column(db.DateTime)
    reject_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    id_hospital = db.Column(db.Text)
    Field18 = db.Column(db.Integer)
    id_department = db.Column(db.Text)
    user_id = db.Column(db.Text)


class MaterialStock(db.Model):
    __tablename__ = 'material_stock'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text)
    model = db.Column(db.Text)
    spec = db.Column(db.Text)
    quantity = db.Column(db.Integer)
    unit = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2))
    remark = db.Column(db.Text)
    updated_at = db.Column(db.DateTime)
    id_hospital = db.Column(db.Text)
    hospital_name = db.Column(db.Text)


class MessageQueue(db.Model):
    __tablename__ = 'message_queue'

    id_message = db.Column(db.Integer, primary_key=True)
    id_workorders = db.Column(db.Text)
    message_type = db.Column(db.Text)
    send_wx = db.Column(db.Integer)


class OutsourcingRecords(db.Model):
    __tablename__ = 'outsourcing_records'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer)
    outsourcing_unit_id = db.Column(db.Integer)
    unit_name = db.Column(db.Text)
    outsourcing_unit_by_dept_id = db.Column(db.Integer)
    outsourcing_unit_by_dept_name = db.Column(db.Text)
    assigned_at = db.Column(db.DateTime)
    vendor_finished_at = db.Column(db.DateTime)
    work_content = db.Column(db.Text)
    quoted_amount = db.Column(db.Numeric(10, 2))
    final_amount = db.Column(db.Numeric(10, 2))
    status = db.Column(db.Integer)
    evaluation_comment = db.Column(db.Text)
    use_department_id = db.Column(db.Integer)
    use_department_name = db.Column(db.Text)
    demand = db.Column(db.Text)
    location = db.Column(db.Text)
    contact_phone = db.Column(db.Text)
    finish_photo = db.Column(db.Text)
    manager_photo = db.Column(db.Text)
    manager_evaluation = db.Column(db.Text)
    remark = db.Column(db.Text)
    final_amount_reason = db.Column(db.Integer)
    use_department_username = db.Column(db.Text)
    cherck_amount_user = db.Column(db.Text)
    manager_department_username = db.Column(db.Text)
    vendor_arrive_at = db.Column(db.Text)


class OutsourcingUnits(db.Model):
    __tablename__ = 'outsourcing_units'

    id = db.Column(db.Integer, primary_key=True)
    unit_name = db.Column(db.Text)
    unit_desc = db.Column(db.Text)
    id_department = db.Column(db.Integer)
    department_name = db.Column(db.Text)
    id_hospital = db.Column(db.Integer)
    hospital_name = db.Column(db.Text)
    status = db.Column(db.Integer)


class Roster(db.Model):
    __tablename__ = 'roster'

    id = db.Column(db.Integer, primary_key=True)
    roster_date = db.Column(db.Text)
    shift_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer)
    department_id = db.Column(db.Integer)


class ScheduleRotation(db.Model):
    __tablename__ = 'schedule_rotation'

    dept_id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.Integer)


class ShiftSettings(db.Model):
    __tablename__ = 'shift_settings'

    id = db.Column(db.Integer, primary_key=True)
    id_department = db.Column(db.Text)
    name = db.Column(db.Text)
    color = db.Column(db.Text)
    start_time = db.Column(db.Text)
    end_time = db.Column(db.Text)
    is_next_day = db.Column(db.Integer)
    workday_mode = db.Column(db.Text)
    weekend_mode = db.Column(db.Text)
    duty_count = db.Column(db.Integer)
    fixed_user_ids = db.Column(db.Text)
    exclude_user_ids = db.Column(db.Text)


class TaskType(db.Model):
    __tablename__ = 'task_type'

    id = db.Column(db.Integer, primary_key=True)
    task_name = db.Column(db.Text)
    description = db.Column(db.Text)
    score = db.Column(db.Integer)
    baseline_time = db.Column(db.Integer)
    key_word = db.Column(db.Text)


class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text)
    password = db.Column(db.Text)
    role = db.Column(db.Text)
    id_hospital = db.Column(db.Text)
    id_department = db.Column(db.Text)
    staff_flag = db.Column(db.Integer)
    user_devices_id = db.Column(db.Text)


class WorkOrderLogs(db.Model):
    __tablename__ = 'work_order_logs'

    id = db.Column(db.Integer, primary_key=True)
    work_id = db.Column(db.Text)
    operator_name = db.Column(db.Text)
    action = db.Column(db.Text)
    prev_status = db.Column(db.Integer)
    curr_status = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.Text)
    staff = db.Column(db.Text)


class WorkOrders(db.Model):
    __tablename__ = 'work_orders'

    id = db.Column(db.Text, primary_key=True)
    source = db.Column(db.Text)
    work_department = db.Column(db.Text)
    demand = db.Column(db.Text)
    work_type = db.Column(db.Text)
    location = db.Column(db.Text)
    task_type = db.Column(db.Text)
    contact_phone = db.Column(db.Text)
    report_photo = db.Column(db.Text)
    staff = db.Column(db.Text)
    work_content = db.Column(db.Text)
    finish_photo = db.Column(db.Text)
    is_rework = db.Column(db.Integer)
    with_device = db.Column(db.Integer)
    feedback = db.Column(db.Text)
    evaluate_score = db.Column(db.Integer)
    remark = db.Column(db.Text)
    status = db.Column(db.Text)
    work_department_name = db.Column(db.Text)
    created_department_name = db.Column(db.Text)
    id_created_hospital = db.Column(db.Integer)
    id_created_department = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    outsource_flag = db.Column(db.Integer)
    task_score = db.Column(db.Integer)
    task_coefficient = db.Column(db.Integer)
    arrival_score = db.Column(db.Integer)
    repair_score = db.Column(db.Integer)
    total_score = db.Column(db.Integer)
    final_score = db.Column(db.Integer)

