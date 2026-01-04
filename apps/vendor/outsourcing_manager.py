import os
import datetime
from flask import render_template, request, jsonify, abort, current_app
from hashids import Hashids
from apps.tools.db import query_db, execute_transaction
from apps.tools.auth import login_required, permission_required
from apps.tools.permissions import get_current_user_info
from .route import bp_vendor 

# --- 配置与常量 ---
hashids = Hashids(salt='1994', min_length=5)
PHOTO_DIR = 'vendor_photo'
LOG_SQL = """
    INSERT INTO work_order_logs 
    (work_id, operator_name, action, prev_status, curr_status, details, created_at, staff)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

# --- 通用辅助函数 ---
def process_row(row):
    """统一处理数据库行转字典及照片字符串解析"""
    if not row: return None
    item = dict(row)
    # 解析供应商照片、管理科室照片
    item['vendor_photos'] = item['finish_photo'].split('丨') if item.get('finish_photo') else []
    item['mgr_photos'] = item['manager_photo'].split('丨') if item.get('manager_photo') else []
    # 别名适配前端模板
    item['photo_list'] = item['vendor_photos'] 
    return item

def save_photos(files, prefix_parts):
    """统一照片保存逻辑。prefix_parts: 用于文件名的标识列表"""
    if not files: return ""
    upload_path = os.path.join(current_app.root_path, PHOTO_DIR)
    if not os.path.exists(upload_path): os.makedirs(upload_path)
    
    time_tag = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    saved_names = []
    
    for idx, file in enumerate(files, start=1):
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            # 命名规则: [标识1]_[时间]_[序号]_[标识2].ext
            filename = f"{'_'.join(map(str, prefix_parts))}_{time_tag}_{idx}{ext}"
            file.save(os.path.join(upload_path, filename))
            saved_names.append(filename)
    return '丨'.join(saved_names)


# ==========================================
# 1. 委外供应商端 (Portal & API)
# ==========================================

@bp_vendor.route('/portal/<hash_str>')
def vendor_portal(hash_str):
    """供应商专属移动端首页"""
    decoded = hashids.decode(hash_str)
    if not decoded: abort(404)
    unit_id = decoded[0]
    
    unit_info = query_db("SELECT * FROM outsourcing_units WHERE id = ?", (unit_id,), one=True)
    if not unit_info: abort(404)

    # 状态逻辑：进行中(<32)在前，已提交(>=32)在后
    sql = "SELECT * FROM outsourcing_records WHERE outsourcing_unit_id = ? ORDER BY CASE WHEN status < 32 THEN 0 ELSE 1 END, assigned_at DESC"
    records = query_db(sql, (unit_id,))
    orders = [process_row(r) for r in records]

    return render_template('vendor/mobile_portal.html', unit=unit_info, orders=orders, hash_str=hash_str, role='vendor')

@bp_vendor.route('/api/update_status', methods=['POST'])
def vendor_api_update():
    """供应商操作：确认到达(12->22) 或 提交完工(22->32)"""
    rec_id = request.form.get('id')
    action = request.form.get('action')
    record = query_db("SELECT * FROM outsourcing_records WHERE id = ?", (rec_id,), one=True)
    if not record: return jsonify({'code': 1, 'msg': '记录不存在'})
    wid, v_name, now_str = record['work_order_id'], record['unit_name'], datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ops = []
    if action == 'arrive':
        ops.append(("UPDATE outsourcing_records SET status=22, vendor_arrive_at=? WHERE id=?", (now_str, rec_id)))
        ops.append(("UPDATE work_orders SET status='22' WHERE id=?", (wid,)))
        ops.append((LOG_SQL, (wid, v_name, '委外到达', '12', '22', f"供应商【{v_name}】已到达现场，时间：{now_str}", now_str, v_name)))
    
    elif action == 'finish':
        content = request.form.get('work_content')
        amount = request.form.get('quoted_amount')
        files = request.files.getlist('photos[]')
        
        if not content or not amount or not files: return jsonify({'code': 1, 'msg': '请填写实施详情、申报报价并上传照片'})
        
        photo_str = save_photos(files, [record['outsourcing_unit_id'], rec_id])
        ops.append(("UPDATE outsourcing_records SET status=32, work_content=?, quoted_amount=?, vendor_finished_at=?, finish_photo=? WHERE id=?", 
                    (content, amount, now_str, photo_str, rec_id)))
        ops.append(("UPDATE work_orders SET status='32', work_content=? WHERE id=?", (content, wid)))
        ops.append((LOG_SQL, (wid, v_name, '委外完工', '22', '32', f"供应商申报完工，金额：{amount}", now_str, v_name)))
    
    success, err = execute_transaction(ops)
    return jsonify({'code': 0, 'msg': '提交成功'}) if success else jsonify({'code': 1, 'msg': str(err)})


# ==========================================
# 2. 需求科室端 (验收审核)
# ==========================================
@bp_vendor.route('/use_acceptance')
@permission_required('SA','GA','HA','HP','DA','DH','ST')
def dept_acceptance_list():
    user = get_current_user_info()
    dept_id = user.get('id_department')
    # ✅ 修正点：必须是 >= 32，才能查出 33, 34, 35 的数据
    sql = "SELECT * FROM outsourcing_records WHERE use_department_id = ? AND status >= 32 ORDER BY CASE WHEN status = 32 THEN 0 ELSE 1 END, assigned_at DESC"
    records = query_db(sql, (dept_id,))
    return render_template('vendor/use_acceptance.html', records=[process_row(r) for r in records], user=user, role='dept')


@bp_vendor.route('/dept/api/confirm', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH','ST')
def dept_api_confirm():
    user = get_current_user_info()
    rec_id = request.form.get('id')
    action = request.form.get('action') # 'pass' or 'reject'
    # 1. 获取前端提交的意见，去除首尾空格
    raw_comment = request.form.get('comment', '').strip()
    # 2. 根据操作类型设置 状态、标题 和 默认意见
    if action == 'pass':
        target_status = 33
        act_title = '需求科室通过'
        # 如果通过且没填意见，默认为“通过验收”
        comment = raw_comment if raw_comment else '通过验收'
    else:
        # 驳回逻辑
        target_status = 12 # 驳回后状态回到 12 (待接单/已派单) 或者 22 (视业务需求而定，通常驳回给供应商重做是回退状态)
        act_title = '需求科室驳回'
        comment = '【驳回】'+raw_comment if raw_comment else '驳回整改'
    # 3. 校验权限
    record = query_db("SELECT * FROM outsourcing_records WHERE id = ?", (rec_id,), one=True)
    if not record or str(record['use_department_id']) != str(user.get('id_department')):
        return jsonify({"code": 1, "msg": "校验失败或无权操作"})
    wid, now_str = record['work_order_id'], datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    ops = [
        # 4. 关键点：这里将 comment 写入 evaluation_comment 字段
        ("UPDATE outsourcing_records SET status=?, evaluation_comment=?, use_department_username=? WHERE id=?", 
         (target_status, 
          comment,
          user['username'], 
          rec_id)),
        # 同步更新主工单状态
        ("UPDATE work_orders SET status=? WHERE id=?", (str(target_status), wid)),
        # 写日志
        (LOG_SQL, (wid, user['username'], act_title, 32, target_status, f"意见：{comment}", now_str, user['username']))
    ]
    
    success, err = execute_transaction(ops)
    return jsonify({'code': 0, 'msg': '操作成功'}) if success else jsonify({'code': 1, 'msg': str(err)})

# ==========================================
# 3. 管理科室端 (现场核实)
# ==========================================

@bp_vendor.route('/manager/acceptance')
@permission_required('SA','GA','HA','HP','DA','DH','ST')
def manager_acceptance_list():
    user = get_current_user_info()
    dept_id = user.get('id_department')
    sql = "SELECT * FROM outsourcing_records WHERE outsourcing_unit_by_dept_id = ? AND status >= 33 ORDER BY CASE WHEN status = 33 THEN 0 ELSE 1 END, assigned_at DESC"
    records = query_db(sql, (dept_id,))
    return render_template('vendor/manager_acceptance.html', records=[process_row(r) for r in records], user=user, role='manager')

@bp_vendor.route('/manager/api/confirm', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH','ST')
def manager_api_confirm():
    user = get_current_user_info()
    rec_id, comment = request.form.get('id'), request.form.get('comment', '').strip()
    files = request.files.getlist('photos[]')
    
    record = query_db("SELECT * FROM outsourcing_records WHERE id = ?", (rec_id,), one=True)
    if not record or record['status'] != 33: return jsonify({"code": 1, "msg": "状态错误"})
    if not comment or not files: return jsonify({"code": 1, "msg": "请填写核验结论并上传照片"})

    photo_str = save_photos(files, [rec_id, 'MGR', user.get('id_department')])
    wid, now_str = record['work_order_id'], datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    ops = [
        ("UPDATE outsourcing_records SET status=34, manager_photo=?,manager_department_username=?, manager_evaluation=? WHERE id=?", 
         ( photo_str,
           user['username'],
           comment,
           rec_id)),
        ("UPDATE work_orders SET status='3' WHERE id=?", (wid,)), # 主单完结标识
        (LOG_SQL, (wid, user['username'], '管理科室核验', 33, 34, f"结论：{comment}", now_str, user['username']))
    ]
    success, err = execute_transaction(ops)
    return jsonify({'code': 0, 'msg': '核验成功，进入审价环节'}) if success else jsonify({'code': 1, 'msg': str(err)})


# ==========================================
# 4. 核价审定端 (科长审定)
# ==========================================

@bp_vendor.route('/manager/check_price')
@permission_required('DH')
def check_price_list():
    user = get_current_user_info()
    sql = "SELECT * FROM outsourcing_records WHERE status IN (34, 35) ORDER BY CASE WHEN status = 34 THEN 0 ELSE 1 END, assigned_at DESC"
    records = query_db(sql)
    return render_template('vendor/check_price.html', records=[process_row(r) for r in records], user=user, role='auditor')

@bp_vendor.route('/manager/api/submit_price', methods=['POST'])
@permission_required('DH')
def api_submit_price():
    user = get_current_user_info()
    rec_id = request.form.get('id')
    final_amount = request.form.get('final_amount')
    reason = request.form.get('final_amount_reason', '准予通过').strip()
    record = query_db("SELECT * FROM outsourcing_records WHERE id = ?", (rec_id,), one=True)
    true_status = query_db("SELECT status FROM work_orders WHERE id = ?", (record['work_order_id'],), one=True)
    if not record or record['status'] != 34: return jsonify({"code": 1, "msg": "状态错误"})
    wid, now_str = record['work_order_id'], datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ops = [
        ("UPDATE outsourcing_records SET final_amount=?, final_amount_reason=?, status=35, cherck_amount_user=? WHERE id=?", 
         (final_amount, reason, user['username'], rec_id)),
        (LOG_SQL, (wid, user['username'], '最终核价', 34, true_status['status'], f"审定价：{final_amount}，理由：{reason}", now_str, user['username']))
    ]
    success, err = execute_transaction(ops)
    return jsonify({'code': 0, 'msg': '核价完成'}) if success else jsonify({'code': 1, 'msg': str(err)})