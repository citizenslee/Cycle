# task_type.py 任务类型管理页面
import math
from flask import render_template, request, jsonify
from apps.tools.auth import login_required, permission_required
# 引入数据库工具
from apps.tools.db import query_db, modify_db
from .route import bp_orders

# ------------------------------------------------
# 1. 页面渲染 (入口)
# ------------------------------------------------
@bp_orders.route('/task_type') # 建议URL去掉.py后缀，保持RESTful风格，原'/task_type.py'也可

@permission_required('SA','GA','HA','HP','DA','DH','SE','PA')
def task_type_index():
    return render_template("orders/task_type.html")

# ------------------------------------------------
# 2. API: 获取数据列表 (Layui 表格数据源)
# ------------------------------------------------
@bp_orders.route('/task_type/list', methods=['GET'])
@permission_required('SA','GA','HA','HP','DA','DH','SE','PA')
def task_type_list():
    try:
        # 获取分页参数，Layui 默认传 page 和 limit
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        offset = (page - 1) * limit

        # 获取搜索参数
        keyword = request.args.get('keyword', '').strip()

        # 构建查询 SQL
        sql_count = "SELECT COUNT(*) as count FROM task_type"
        sql_data = "SELECT * FROM task_type"
        params = []

        if keyword:
            where_clause = " WHERE task_name LIKE ? OR description LIKE ? OR key_word LIKE ?"
            sql_count += where_clause
            sql_data += where_clause
            search_term = f"%{keyword}%"
            params = [search_term, search_term, search_term]

        sql_data += " ORDER BY id DESC LIMIT ? OFFSET ?"
        data_params = params + [limit, offset]

        # 执行查询
        total_row = query_db(sql_count, params, one=True)
        total = total_row['count'] if total_row else 0
        
        rows = query_db(sql_data, data_params)

        # Layui 要求的标准格式
        return jsonify({
            "code": 0,
            "msg": "",
            "count": total,
            "data": rows  # query_db 返回的是字典列表，可以直接 json 化
        })

    except Exception as e:
        print(f"Task Type List Error: {e}")
        return jsonify({"code": 1, "msg": "数据加载失败"})

# ------------------------------------------------
# 3. API: 新增任务类型
# ------------------------------------------------
@bp_orders.route('/task_type/add', methods=['POST'])
@permission_required('SA','GA','HA','HP')
def task_type_add():
    try:
        task_name = request.form.get('task_name')
        description = request.form.get('description')
        score = request.form.get('score', 0)
        baseline_time = request.form.get('baseline_time', 0)
        key_word = request.form.get('key_word', '')

        if not task_name:
            return jsonify({"code": 1, "msg": "任务名称不能为空"})

        sql = """
            INSERT INTO task_type (task_name, description, score, baseline_time, key_word) 
            VALUES (?, ?, ?, ?, ?)
        """
        success, res = modify_db(sql, (task_name, description, score, baseline_time, key_word))
        
        if success:
            return jsonify({"code": 0, "msg": "添加成功"})
        else:
            return jsonify({"code": 1, "msg": f"添加失败: {res}"})

    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})

# ------------------------------------------------
# 4. API: 编辑任务类型
# ------------------------------------------------
@bp_orders.route('/task_type/edit', methods=['POST'])
@permission_required('SA','GA','HA','HP')
def task_type_edit():
    try:
        data_id = request.form.get('id')
        task_name = request.form.get('task_name')
        description = request.form.get('description')
        score = request.form.get('score')
        baseline_time = request.form.get('baseline_time')
        key_word = request.form.get('key_word', '')

        if not data_id:
            return jsonify({"code": 1, "msg": "ID缺失"})

        sql = """
            UPDATE task_type 
            SET task_name=?, description=?, score=?, baseline_time=?, key_word=? 
            WHERE id=?
        """
        success, res = modify_db(sql, (task_name, description, score, baseline_time, key_word, data_id))

        if success:
            return jsonify({"code": 0, "msg": "修改成功"})
        else:
            return jsonify({"code": 1, "msg": f"修改失败: {res}"})

    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})

# ------------------------------------------------
# 5. API: 删除任务类型
# ------------------------------------------------
@bp_orders.route('/task_type/del', methods=['POST'])
@permission_required('SA','GA','HA','HP')
def task_type_del():
    try:
        data_id = request.form.get('id')
        if not data_id:
            return jsonify({"code": 1, "msg": "ID缺失"})

        sql = "DELETE FROM task_type WHERE id=?"
        success, res = modify_db(sql, (data_id,))

        if success:
            return jsonify({"code": 0, "msg": "删除成功"})
        else:
            return jsonify({"code": 1, "msg": "删除失败"})

    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})