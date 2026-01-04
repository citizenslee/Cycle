# hospital_manger.py 医院管理界面
from flask import render_template, request, jsonify
from .route import bp_system 
from apps.tools.auth import login_required, permission_required
from apps.tools.db import query_db,modify_db


@bp_system.route('/hospital_manger')
@permission_required('SA','GA')
def hospital_manger():
    return render_template("system/hospital_manger.html")

# 院区管理 API
@bp_system.route('/api/hospital', methods=['GET', 'POST', 'PUT', 'DELETE'])
@permission_required('SA','GA')
def api_hospital():
    if request.method == 'GET':
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        offset = (page - 1) * limit

        # 1. 查询总数
        count_sql = "SELECT COUNT(*) as total FROM hospital"
        total_res = query_db(count_sql, one=True)
        total = total_res['total'] if total_res else 0

        # 2. 分页查询数据
        data_sql = "SELECT * FROM hospital LIMIT ? OFFSET ?"
        data = query_db(data_sql, (limit, offset))
        
        return jsonify({"code": 0, "msg": "", "count": total, "data": data})

    elif request.method == 'POST':
        data = request.json
        sql = "INSERT INTO hospital (area_name, hospital_name) VALUES (?, ?)"
        success, res = modify_db(sql, (data.get('area_name'), data.get('hospital_name')))
        
        if success:
            return jsonify({"code": 0, "msg": "添加成功"})
        return jsonify({"code": 1, "msg": f"添加失败: {res}"})

    elif request.method == 'PUT':
        data = request.json
        sql = "UPDATE hospital SET area_name=?, hospital_name=? WHERE id_hospital=?"
        success, res = modify_db(sql, (data.get('area_name'), data.get('hospital_name'), data.get('id_hospital')))
        
        if success:
            return jsonify({"code": 0, "msg": "修改成功"})
        return jsonify({"code": 1, "msg": "修改失败"})

    elif request.method == 'DELETE':
            id_ = request.json.get('id_hospital')
            
            # 1. 【新增逻辑】检查该医院下是否存在科室
            # 统计 department 表中该 id_hospital 的记录数
            check_sql = "SELECT COUNT(*) as count FROM department WHERE id_hospital = ?"
            check_res = query_db(check_sql, (id_,), one=True)
            
            # 如果查询结果存在且数量大于0，则拦截删除
            if check_res and check_res['count'] > 0:
                return jsonify({
                    "code": 1, 
                    "msg": f"操作失败：该医院下仍存在 {check_res['count']} 个科室，请先删除或转移科室数据。"
                })

            # 2. 执行删除
            sql = "DELETE FROM hospital WHERE id_hospital=?"
            success, res = modify_db(sql, (id_,))
            
            if success:
                return jsonify({"code": 0, "msg": "删除成功"})
            return jsonify({"code": 1, "msg": f"删除失败: {res}"})

