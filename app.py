# 主启动文件
from flask import Flask, g
from flask_wtf.csrf import CSRFProtect
from datetime import timedelta
from apps.tools.extensions import db # 从新文件导入
import os

app = Flask(__name__)


# 获取当前文件的绝对目录
basedir = os.path.abspath(os.path.dirname(__file__))

# ------- 1. 配置加载 (建议放在最前) -------
app.config["SECRET_KEY"] = "Li9991QCDCGRE1*啊"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)
app.config["WTF_CSRF_CHECK_DEFAULT"] = False 

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'workorders.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

# ------- 2. 初始化插件 -------
# 全局的 SQLAlchemy 对象

csrf = CSRFProtect(app)
db.init_app(app)
# ------- 3. 注册蓝图 (关键修改：移到 db 初始化之后) -------
# 为什么要放这里？
# 因为蓝图文件(bp_orders等)内部可能会引用上面的 'db' 对象。
# 如果放在最开头导入，蓝图引用 'db' 时，'db' 还没生成，就会报错。

from apps.index.index import bp_index
from apps.tools.login import bp_login
from apps.system.route import bp_system
from apps.orders.route import bp_orders
from apps.devices.route import bp_devices
from apps.materials.materials import bp_materials
from apps.vendor.route import bp_vendor
from apps.tools.photo_view import bp_photo_view
from apps.schedule.route import bp_schedule

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 注册所有蓝图
app.register_blueprint(bp_index)
app.register_blueprint(bp_system)
app.register_blueprint(bp_orders)
app.register_blueprint(bp_devices)
app.register_blueprint(bp_materials)
app.register_blueprint(bp_login)
app.register_blueprint(bp_vendor)
app.register_blueprint(bp_photo_view)
app.register_blueprint(bp_schedule)

print(app.url_map)

# ------- 4. 旧版 SQLite 连接关闭处理 -------
# 这个函数只处理 g._database (原来的 raw sql 连接)
# SQLAlchemy 会自动管理它自己的连接，不需要你手动 close
@app.teardown_appcontext
def close_raw_connection(exception):
    # 改个名字叫 raw_conn，避免和上面的 db 对象混淆
    raw_conn = getattr(g, '_database', None)
    if raw_conn is not None:
        raw_conn.close()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=80, debug=True)