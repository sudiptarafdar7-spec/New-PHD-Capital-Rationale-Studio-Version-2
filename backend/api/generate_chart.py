"""
Generate Chart API - Standalone chart generation tool
No database records required - generates charts on demand and auto-cleans up
"""
from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required
from datetime import datetime
import os
import uuid
from backend.api import Blueprint
from backend.services.manual_v2.utils import get_stock_autocomplete, get_master_csv_path
from backend.services.chart_generator import ChartGeneratorService
import pandas as pd

generate_chart_bp = Blueprint('generate_chart', __name__, url_prefix='/api/v1/generate-chart')

CHARTS_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'generated_charts')
os.makedirs(CHARTS_FOLDER, exist_ok=True)


@generate_chart_bp.route('/stocks', methods=['GET'])
@jwt_required()
def autocomplete_stocks():
    """Stock symbol autocomplete from master CSV"""
    try:
        query = request.args.get('q') or request.args.get('query', '')
        query = query.strip() if query else ''
        limit = request.args.get('limit', 10, type=int)
        
        if not query:
            return jsonify({'stocks': []}), 200
        
        stocks = get_stock_autocomplete(query, limit)
        
        return jsonify({'stocks': stocks}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@generate_chart_bp.route('/stock-details', methods=['GET'])
@jwt_required()
def get_stock_details():
    """Get full stock details from master CSV by symbol"""
    try:
        symbol = request.args.get('symbol', '').strip().upper()
        
        if not symbol:
            return jsonify({'error': 'Symbol is required'}), 400
        
        master_csv_path = get_master_csv_path()
        if not master_csv_path or not os.path.exists(master_csv_path):
            return jsonify({'error': 'Master CSV file not found'}), 404
        
        df = pd.read_csv(master_csv_path)
        df_equity = df[
            (df['SEM_INSTRUMENT_NAME'] == 'EQUITY') & 
            (df['SEM_EXCH_INSTRUMENT_TYPE'] == 'ES')
        ].copy()
        
        matching_row = df_equity[
            df_equity['SEM_TRADING_SYMBOL'].str.upper() == symbol
        ]
        
        if matching_row.empty:
            return jsonify({'error': f"Stock symbol '{symbol}' not found"}), 404
        
        row = matching_row.iloc[0]
        
        stock_details = {
            'symbol': str(row['SEM_TRADING_SYMBOL']) if pd.notna(row['SEM_TRADING_SYMBOL']) else '',
            'security_id': str(row['SEM_SMST_SECURITY_ID']) if pd.notna(row['SEM_SMST_SECURITY_ID']) else '',
            'listed_name': str(row['SM_SYMBOL_NAME']) if pd.notna(row['SM_SYMBOL_NAME']) else '',
            'short_name': str(row['SEM_CUSTOM_SYMBOL']) if pd.notna(row['SEM_CUSTOM_SYMBOL']) else '',
            'exchange': str(row['SEM_EXM_EXCH_ID']) if pd.notna(row['SEM_EXM_EXCH_ID']) else ''
        }
        
        return jsonify({'stock': stock_details}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@generate_chart_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_chart():
    """Generate a stock chart"""
    try:
        data = request.get_json()
        
        symbol = data.get('symbol', '').strip().upper()
        security_id = data.get('security_id', '').strip()
        short_name = data.get('short_name', '').strip()
        exchange = data.get('exchange', 'NSE').strip().upper()
        chart_type = data.get('chart_type', 'Daily').strip()
        date_str = data.get('date', '').strip()
        time_str = data.get('time', '').strip()
        
        if not symbol:
            return jsonify({'error': 'Stock symbol is required'}), 400
        
        if not security_id:
            return jsonify({'error': 'Security ID is required'}), 400
        
        if not date_str:
            return jsonify({'error': 'Date is required'}), 400
        
        if not time_str:
            time_str = '15:30:00'
        
        if chart_type not in ['Daily', 'Weekly', 'Monthly']:
            chart_type = 'Daily'
        
        chart_service = ChartGeneratorService()
        result = chart_service.generate_chart(
            security_id=security_id,
            symbol=symbol,
            short_name=short_name or symbol,
            exchange=exchange,
            chart_type=chart_type,
            date_str=date_str,
            time_str=time_str
        )
        
        if result['success']:
            return jsonify({
                'success': True,
                'chart_id': result['chart_id'],
                'chart_url': f"/api/v1/generate-chart/view/{result['chart_id']}",
                'download_url': f"/api/v1/generate-chart/download/{result['chart_id']}",
                'cmp': result.get('cmp'),
                'cmp_datetime': result.get('cmp_datetime')
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to generate chart')
            }), 400
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@generate_chart_bp.route('/view/<chart_id>', methods=['GET'])
@jwt_required()
def view_chart(chart_id):
    """View/display a generated chart (doesn't delete it)"""
    try:
        chart_path = os.path.join(CHARTS_FOLDER, f"{chart_id}.png")
        
        if not os.path.exists(chart_path):
            return jsonify({'error': 'Chart not found or expired'}), 404
        
        return send_file(
            chart_path,
            mimetype='image/png',
            as_attachment=False
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@generate_chart_bp.route('/download/<chart_id>', methods=['GET'])
@jwt_required()
def download_chart(chart_id):
    """Download a generated chart and delete it from server"""
    try:
        chart_path = os.path.join(CHARTS_FOLDER, f"{chart_id}.png")
        
        if not os.path.exists(chart_path):
            return jsonify({'error': 'Chart not found or expired'}), 404
        
        response = send_file(
            chart_path,
            mimetype='image/png',
            as_attachment=True,
            download_name=f"chart_{chart_id}.png"
        )
        
        @response.call_on_close
        def delete_chart():
            try:
                if os.path.exists(chart_path):
                    os.remove(chart_path)
                    print(f"🗑️ Chart deleted after download: {chart_id}")
            except Exception as e:
                print(f"⚠️ Error deleting chart: {e}")
        
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@generate_chart_bp.route('/cleanup', methods=['POST'])
@jwt_required()
def cleanup_old_charts():
    """Cleanup charts older than 24 hours (can be called manually or via cron)"""
    try:
        from datetime import timedelta
        
        deleted_count = 0
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        for filename in os.listdir(CHARTS_FOLDER):
            if filename.endswith('.png'):
                file_path = os.path.join(CHARTS_FOLDER, filename)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                if file_mtime < cutoff_time:
                    os.remove(file_path)
                    deleted_count += 1
        
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'message': f'Deleted {deleted_count} old charts'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
