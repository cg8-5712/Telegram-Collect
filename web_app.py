"""
Web 管理界面 - 使用 JWT 认证
"""
import os
import yaml
import logging
import jwt
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, make_response, send_file
from flask_cors import CORS
from functools import wraps

# 导入统计模块
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from src.core.statistics import StatisticsDB
from src.core.monitor import monitor_registry


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
CORS(app)

logger = logging.getLogger("WebApp")

# 配置文件路径
CONFIG_FILE = "config.yaml"


def _parse_proxy_string(proxy_str):
    """将代理字符串 (如 socks5://host:port) 解析为 dict"""
    import re
    m = re.match(r'^(socks5|socks4|http)://([^:]+):(\d+)$', proxy_str)
    if m:
        return {'enabled': True, 'type': m.group(1), 'host': m.group(2), 'port': int(m.group(3))}
    return {}

# 初始化统计数据库
stats_db = StatisticsDB()

# JWT 认证装饰器
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('token')

        if not token:
            return jsonify({'success': False, 'message': '未登录'}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['username']
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token 已过期'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Token 无效'}), 401

        return f(current_user, *args, **kwargs)

    return decorated


@app.route('/')
def index():
    """首页 - 仪表板"""
    token = request.cookies.get('token')
    if not token:
        return render_template('login.html')

    try:
        jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        return render_template('index.html')
    except:
        return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        # 简单的认证（支持环境变量配置）
        # 默认用户名: admin, 密码: admin123
        admin_user = os.environ.get('ADMIN_USER', 'admin')
        admin_pass = os.environ.get('ADMIN_PASS', 'admin123')
        if username == admin_user and password == admin_pass:
            # 生成 JWT token
            token = jwt.encode({
                'username': username,
                'exp': datetime.utcnow() + timedelta(hours=24)  # 24小时过期
            }, app.config['SECRET_KEY'], algorithm="HS256")

            response = make_response(jsonify({'success': True, 'message': '登录成功'}))
            response.set_cookie('token', token, httponly=True, max_age=86400)  # 24小时
            return response
        else:
            return jsonify({'success': False, 'message': '用户名或密码错误'}), 401

    return render_template('login.html')


@app.route('/logout')
def logout():
    """登出"""
    response = make_response(jsonify({'success': True, 'message': '已登出'}))
    response.set_cookie('token', '', expires=0)
    return response


@app.route('/api/config', methods=['GET'])
@token_required
def get_config(current_user):
    """获取配置"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 隐藏敏感信息
        if 'monitor_accounts' in config:
            for acc in config['monitor_accounts']:
                acc['api_hash'] = '***'
        elif 'monitor_account' in config:
            config['monitor_account']['api_hash'] = '***'

        return jsonify({'success': True, 'config': config})
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/config', methods=['POST'])
@token_required
def update_config(current_user):
    """更新配置"""
    try:
        data = request.get_json()

        # 读取现有配置
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 更新配置
        if 'keywords' in data:
            config['keywords'] = data['keywords']
        if 'monitor_groups' in data:
            config['monitor_groups'] = data['monitor_groups']
        if 'notification' in data:
            config['notification'] = data['notification']
        if 'notify_targets' in data:
            config['notify_targets'] = data['notify_targets']
        if 'red_packet' in data:
            config['red_packet'] = data['red_packet']

        # 保存配置
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'success': True, 'message': '配置已更新'})
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/keywords', methods=['GET'])
@token_required
def get_keywords(current_user):
    """获取关键词列表"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        keywords = config.get('keywords', {})
        return jsonify({'success': True, 'keywords': keywords})
    except Exception as e:
        logger.error(f"获取关键词失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/keywords', methods=['POST'])
@token_required
def update_keywords(current_user):
    """更新关键词"""
    try:
        data = request.get_json()

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        config['keywords'] = data

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'success': True, 'message': '关键词已更新'})
    except Exception as e:
        logger.error(f"更新关键词失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/groups', methods=['GET'])
@token_required
def get_groups(current_user):
    """获取群组列表"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        groups = config.get('monitor_groups', [])
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        logger.error(f"获取群组失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/groups', methods=['POST'])
@token_required
def update_groups(current_user):
    """更新群组列表"""
    try:
        data = request.get_json()

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        config['monitor_groups'] = data

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'success': True, 'message': '群组列表已更新'})
    except Exception as e:
        logger.error(f"更新群组失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/status', methods=['GET'])
@token_required
def get_status(current_user):
    """获取系统状态（含多账号在线信息）"""
    try:
        status = {
            'monitor_running': any(v.get('online') for v in monitor_registry.values()),
            'accounts': dict(monitor_registry),  # 每个账号的详细状态
            'accounts_total': len(monitor_registry),
            'accounts_online': sum(1 for v in monitor_registry.values() if v.get('online')),
            'groups_count': 0,
            'keywords_count': 0,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # 读取配置获取实际数据
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        groups = config.get('monitor_groups', [])
        status['groups_count'] = len([g for g in groups if g.get('enabled', True)])

        keywords = config.get('keywords', {})
        status['keywords_count'] = (
            len(keywords.get('exact', [])) +
            len(keywords.get('contains', [])) +
            len(keywords.get('regex', []))
        )

        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/export', methods=['GET'])
@token_required
def export_config(current_user):
    """导出配置"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 隐藏敏感信息
        if 'monitor_accounts' in config:
            for acc in config['monitor_accounts']:
                acc['api_hash'] = '***'
                acc['phone'] = '***'
        elif 'monitor_account' in config:
            config['monitor_account']['api_hash'] = '***'
            config['monitor_account']['phone'] = '***'

        return jsonify({'success': True, 'config': config})
    except Exception as e:
        logger.error(f"导出配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/verify', methods=['GET'])
@token_required
def verify_token(current_user):
    """验证 token 是否有效"""
    return jsonify({'success': True, 'username': current_user})


# ==================== 账号管理 API ====================

@app.route('/api/accounts', methods=['GET'])
@token_required
def get_accounts(current_user):
    """获取账号列表（含实时在线状态）"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        accounts = config.get('monitor_accounts', [])
        # 如果是旧配置格式，转成列表
        if not accounts and 'monitor_account' in config:
            acc = config['monitor_account']
            acc.setdefault('name', '默认账号')
            acc.setdefault('enabled', True)
            accounts = [acc]

        # 合并运行时在线状态
        result = []
        for acc in accounts:
            name = acc.get('name', acc.get('phone', ''))
            registry_info = monitor_registry.get(name, {})
            # 优先取运行时实时值，回退取 config 中存储的 username
            username = registry_info.get('username') or acc.get('username', '')
            proxy_raw = acc.get('proxy', {})
            # proxy 可能是字符串(旧格式)或dict，统一处理
            if isinstance(proxy_raw, str):
                proxy_str = proxy_raw
                proxy_cfg = _parse_proxy_string(proxy_raw)
            elif isinstance(proxy_raw, dict):
                proxy_cfg = proxy_raw
                proxy_str = ''
                if proxy_cfg and proxy_cfg.get('enabled', True) and proxy_cfg.get('host'):
                    proxy_str = f"{proxy_cfg.get('type','socks5')}://{proxy_cfg['host']}:{proxy_cfg.get('port',7890)}"
            else:
                proxy_cfg = {}
                proxy_str = ''
            # 运行时的代理信息覆盖
            runtime_proxy = registry_info.get('proxy')
            result.append({
                'name': name,
                'phone': acc.get('phone', ''),
                'api_id': acc.get('api_id', ''),
                'session_file': acc.get('session_file', ''),
                'enabled': acc.get('enabled', True),
                'online': registry_info.get('online', False),
                'username': username,
                'started_at': registry_info.get('started_at'),
                'proxy': runtime_proxy or proxy_str,
                'proxy_config': proxy_cfg if isinstance(proxy_cfg, dict) else {},  # 结构化代理配置供WebUI编辑
                'region': acc.get('region', ''),  # 地区备注
            })

        return jsonify({'success': True, 'data': result})
    except Exception as e:
        logger.error(f"获取账号列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/accounts', methods=['POST'])
@token_required
def update_accounts(current_user):
    """更新账号列表（新增/编辑/删除/启停）"""
    try:
        data = request.get_json()

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # data 是完整的账号数组
        new_accounts = data if isinstance(data, list) else data.get('accounts', [])

        # 保留原有 api_hash（前端可能传 *** 回来）
        old_accounts = {
            acc.get('name', acc.get('phone', '')): acc
            for acc in config.get('monitor_accounts', [])
        }
        for acc in new_accounts:
            name = acc.get('name', acc.get('phone', ''))
            if acc.get('api_hash') in (None, '', '***') and name in old_accounts:
                acc['api_hash'] = old_accounts[name].get('api_hash', '')

        # 清理前端传回的运行时字段，只保留配置字段
        runtime_fields = ('online', 'started_at', 'proxy_config')
        for acc in new_accounts:
            for field in runtime_fields:
                acc.pop(field, None)
            # 如果 proxy 是空dict或 enabled=false，移除
            proxy = acc.get('proxy')
            if isinstance(proxy, dict) and (not proxy or not proxy.get('enabled', True) or not proxy.get('host')):
                acc.pop('proxy', None)

        config['monitor_accounts'] = new_accounts
        # 如果存在旧格式，清除
        config.pop('monitor_account', None)

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'success': True, 'message': '账号列表已更新'})
    except Exception as e:
        logger.error(f"更新账号失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== 统计相关 API ====================

@app.route('/api/statistics/overview', methods=['GET'])
@token_required
def get_statistics_overview(current_user):
    """获取统计概览"""
    try:
        days = request.args.get('days', 7, type=int)

        # 获取消息统计
        message_stats = stats_db.get_message_stats(days=days)

        # 获取关键词统计（Top 10）
        keyword_stats = stats_db.get_keyword_stats(limit=10)

        # 获取群组统计（Top 10）
        group_stats = stats_db.get_group_stats(limit=10)

        return jsonify({
            'success': True,
            'data': {
                'message_stats': message_stats,
                'keyword_stats': keyword_stats,
                'group_stats': group_stats
            }
        })
    except Exception as e:
        logger.error(f"获取统计概览失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/statistics/messages', methods=['GET'])
@token_required
def get_message_statistics(current_user):
    """获取消息统计"""
    try:
        days = request.args.get('days', 7, type=int)
        stats = stats_db.get_message_stats(days=days)
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"获取消息统计失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/statistics/keywords', methods=['GET'])
@token_required
def get_keyword_statistics(current_user):
    """获取关键词统计"""
    try:
        limit = request.args.get('limit', 10, type=int)
        stats = stats_db.get_keyword_stats(limit=limit)
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"获取关键词统计失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/statistics/groups', methods=['GET'])
@token_required
def get_group_statistics(current_user):
    """获取群组统计"""
    try:
        limit = request.args.get('limit', 10, type=int)
        stats = stats_db.get_group_stats(limit=limit)
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"获取群组统计失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/history', methods=['GET'])
@token_required
def get_history(current_user):
    """获取历史记录"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        group_id = request.args.get('group_id', type=int)
        keyword = request.args.get('keyword')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        result = stats_db.get_history(
            limit=limit,
            offset=offset,
            group_id=group_id,
            keyword=keyword,
            start_date=start_date,
            end_date=end_date
        )

        return jsonify({'success': True, 'data': result})
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/export/data', methods=['GET'])
@token_required
def export_data(current_user):
    """导出数据为 CSV"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        data = stats_db.export_data(start_date=start_date, end_date=end_date)

        # 创建 CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # 写入表头
        writer.writerow(['ID', '群组ID', '群组名称', '消息内容', '发送者ID', '发送者名称', '匹配关键词', '创建时间'])

        # 写入数据
        for record in data:
            writer.writerow([
                record['id'],
                record['group_id'],
                record['group_name'],
                record['message_text'],
                record['sender_id'],
                record['sender_name'],
                record['matched_keyword'],
                record['created_at']
            ])

        # 创建响应
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),  # 使用 utf-8-sig 支持中文
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'statistics_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    except Exception as e:
        logger.error(f"导出数据失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== 红包相关 API ====================

@app.route('/api/red_packet/config', methods=['GET'])
@token_required
def get_red_packet_config(current_user):
    """获取红包配置"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        rp_config = config.get('red_packet', {})
        return jsonify({'success': True, 'data': rp_config})
    except Exception as e:
        logger.error(f"获取红包配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/red_packet/config', methods=['POST'])
@token_required
def update_red_packet_config(current_user):
    """更新红包配置"""
    try:
        data = request.get_json()

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        config['red_packet'] = data

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'success': True, 'message': '红包配置已更新'})
    except Exception as e:
        logger.error(f"更新红包配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/red_packet/stats', methods=['GET'])
@token_required
def get_red_packet_stats(current_user):
    """获取红包统计概览"""
    try:
        days = request.args.get('days', 7, type=int)
        stats = stats_db.get_red_packet_stats(days=days)
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"获取红包统计失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/red_packet/history', methods=['GET'])
@token_required
def get_red_packet_history(current_user):
    """获取红包领取历史"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        group_id = request.args.get('group_id', type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # 获取账号筛选参数
        accounts_param = request.args.get('accounts')
        account_names = None
        if accounts_param and accounts_param != 'all':
            account_names = [name.strip() for name in accounts_param.split(',') if name.strip()]

        result = stats_db.get_red_packet_history(
            limit=limit,
            offset=offset,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date,
            account_names=account_names
        )
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        logger.error(f"获取红包历史失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/red_packet/calendar', methods=['GET'])
@token_required
def get_red_packet_calendar(current_user):
    """获取红包日历数据"""
    try:
        now = datetime.now()
        year = request.args.get('year', now.year, type=int)
        month = request.args.get('month', now.month, type=int)

        calendar_data = stats_db.get_red_packet_calendar(year=year, month=month)
        return jsonify({'success': True, 'data': calendar_data, 'year': year, 'month': month})
    except Exception as e:
        logger.error(f"获取红包日历失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/red_packet/stats_by_account', methods=['GET'])
@token_required
def get_red_packet_stats_by_account(current_user):
    """获取按账号分组的红包统计"""
    try:
        days = request.args.get('days', 7, type=int)
        stats = stats_db.get_red_packet_stats_by_account(days=days)
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"获取账号红包统计失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def run_web_app(host='0.0.0.0', port=5000, debug=False):
    """运行 Web 应用"""
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_web_app(debug=True)
