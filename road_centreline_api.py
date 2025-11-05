"""
香港道路中心線查詢服務
從 CSDI WFS 服務獲取道路中心線資料，用於地圖匹配與電子圍欄判定
"""

from flask import Flask, request, jsonify
import requests
import json


# 創建獨立的 Flask 應用
app = Flask(__name__)

# WFS 服務配置
WFS_BASE_URL = 'https://portal.csdi.gov.hk/server/services/common/landsd_rcd_1637310758814_80061/MapServer/WFSServer'
FEATURE_TYPE = 'csdi:RoadCentreLine'


@app.route('/health', methods=['GET'])
def health_check():
    """健康檢查端點"""
    return jsonify({'status': 'road centreline service healthy'})


@app.route('/get_road_centreline', methods=['POST'])
def get_road_centreline():
    """
    從 CSDI WFS 服務獲取香港道路中心線資料
    
    請求參數（JSON）:
        {
            "bbox": [minx, miny, maxx, maxy],  # 可選，邊界框 (EPSG:2326)
            "format": "geojson"  # 可選，輸出格式：geojson, json, gml, kml (預設 geojson)
        }
    
    返回:
        GeoJSON 格式的道路中心線數據
    """
    try:
        if not request.is_json:
            return jsonify({
                'result': '1',
                'resultMessage': '請提供JSON格式資料'
            }), 400
        
        data = request.get_json() or {}
        
        format_preference = data.get('format', 'geojson').lower()
        
        # 根據 WFS GetCapabilities，對應不同輸出格式
        output_format_map = {
            'geojson': 'application/json',
            'json': 'application/json',
            'gml': 'application/gml+xml; version=3.2',
            'kml': 'application/vnd.google-earth.kml+xml'
        }
        output_format = output_format_map.get(format_preference, 'application/json')
        
        # 構建 WFS GetFeature 請求參數
        wfs_params = {
            'service': 'WFS',
            'version': '2.0.0',
            'request': 'GetFeature',
            'typeNames': FEATURE_TYPE,
            'outputFormat': output_format,
            'srsName': 'EPSG:2326'  # 香港1980網格系統
        }
        
        # 如果提供了 bbox，添加到參數中
        bbox = data.get('bbox')
        if bbox:
            if not isinstance(bbox, list) or len(bbox) != 4:
                return jsonify({
                    'result': '1',
                    'resultMessage': 'bbox 必須為包含4個數字的陣列 [minx, miny, maxx, maxy]'
                }), 400
            
            try:
                minx, miny, maxx, maxy = [float(x) for x in bbox]
                # WFS 2.0 bbox 格式: bbox=minx,miny,maxx,maxy,srs
                wfs_params['bbox'] = f'{minx},{miny},{maxx},{maxy},EPSG:2326'
            except (ValueError, TypeError):
                return jsonify({
                    'result': '1',
                    'resultMessage': 'bbox 中的值必須為數字'
                }), 400
        
        # 發送 WFS 請求
        resp = requests.get(WFS_BASE_URL, params=wfs_params, timeout=30)
        resp.raise_for_status()
        
        # 解析回應
        try:
            result_data = resp.json()
            
            return jsonify({
                'result': '0',
                'resultMessage': 'Success',
                'data': result_data,
                'feature_count': len(result_data.get('features', [])) if isinstance(result_data, dict) else 0
            }), 200
        except ValueError:
            # 如果不是 JSON，返回原始文本
            return jsonify({
                'result': '0',
                'resultMessage': 'Success',
                'data': resp.text,
                'raw': True
            }), 200
            
    except requests.HTTPError as http_err:
        return jsonify({
            'result': '1',
            'resultMessage': f'WFS 服務 HTTP 錯誤: {str(http_err)}'
        }), 502
    except requests.RequestException as req_err:
        return jsonify({
            'result': '1',
            'resultMessage': f'WFS 請求錯誤: {str(req_err)}'
        }), 502
    except Exception as e:
        return jsonify({
            'result': '1',
            'resultMessage': f'伺服器錯誤: {str(e)}'
        }), 500


@app.route('/get_capabilities', methods=['GET'])
def get_capabilities():
    """
    獲取 WFS 服務的能力描述（GetCapabilities）
    
    返回:
        WFS Capabilities XML 或解析後的結構
    """
    try:
        wfs_params = {
            'service': 'WFS',
            'version': '2.0.0',
            'request': 'GetCapabilities'
        }
        
        resp = requests.get(WFS_BASE_URL, params=wfs_params, timeout=30)
        resp.raise_for_status()
        
        return jsonify({
            'result': '0',
            'resultMessage': 'Success',
            'data': resp.text,
            'content_type': resp.headers.get('Content-Type', '')
        }), 200
        
    except Exception as e:
        return jsonify({
            'result': '1',
            'resultMessage': f'伺服器錯誤: {str(e)}'
        }), 500


if __name__ == '__main__':
    # 獨立運行時使用的配置
    app.run(host='0.0.0.0', port=5008, debug=True)

