"""
報告生成器模組 - 生成 HTML 格式的視覺化報告
"""
from typing import Dict, List
from pathlib import Path
import json
from datetime import datetime, timedelta
from .holdings_analyzer import HoldingChange


class HTMLReportGenerator:
    """HTML 報告生成器（提案 B：圖表視覺化式）"""
    
    def __init__(self, output_dir: Path = None):
        """
        初始化報告生成器
        
        Args:
            output_dir: 輸出目錄，預設為 docs/
        """
        self.output_dir = output_dir or Path("docs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_dashboard_data(
        self, 
        changes_dict: Dict[str, List[HoldingChange]], 
        date: str,
        etf_info_dict: Dict[str, str],
        etf_holdings: List[dict] = None
    ) -> dict:
        """
        生成儀表板所需的 JSON 資料
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            etf_info_dict: ETF代碼 -> ETF名稱的字典
            
        Returns:
            dict: 包含所有圖表資料的字典
        """
        total_changes = sum(len(changes) for changes in changes_dict.values())
        
        # 1. 變動分布數據（圓餅圖）
        change_distribution = []
        for etf_code, changes in sorted(changes_dict.items()):
            etf_name = etf_info_dict.get(etf_code, etf_code)
            change_distribution.append({
                'etf_code': etf_code,
                'etf_name': etf_name,
                'count': len(changes)
            })
        
        # 2. 熱門調整股票統計
        stock_changes = {}  # stock_code -> {name, up_count, down_count, net_change, etf_details}
        
        for etf_code, changes in changes_dict.items():
            etf_name = etf_info_dict.get(etf_code, etf_code)
            for change in changes:
                if change.change_type in ['SHARES_UP', 'SHARES_DOWN']:
                    code = change.stock_code
                    if code not in stock_changes:
                        stock_changes[code] = {
                            'name': change.stock_name,
                            'up_count': 0,
                            'down_count': 0,
                            'net_change': 0,
                            'etf_details': []
                        }
                    
                    # 記錄 ETF 調整詳情
                    etf_detail = {
                        'etf_code': etf_code,
                        'etf_name': etf_name,
                        'adjustment': round(change.lots_diff, 2),
                        'new_lots': round(change.new_lots, 2)
                    }
                    stock_changes[code]['etf_details'].append(etf_detail)
                    
                    if change.change_type == 'SHARES_UP':
                        stock_changes[code]['up_count'] += 1
                        stock_changes[code]['net_change'] += change.lots_diff
                    else:
                        stock_changes[code]['down_count'] += 1
                        stock_changes[code]['net_change'] += change.lots_diff
        
        # 補充權重資訊
        if etf_holdings:
            for stock_code, stock_data in stock_changes.items():
                for etf_detail in stock_data['etf_details']:
                    etf_code = etf_detail['etf_code']
                    # 在 etf_holdings 中找到對應的 ETF
                    for etf in etf_holdings:
                        if etf['etf_code'] == etf_code:
                            # 在該 ETF 的持股中找到對應的股票
                            for holding in etf.get('holdings', []):
                                if holding.get('stock_code') == stock_code:
                                    etf_detail['weight'] = holding.get('weight', 0)
                                    etf_detail['lots'] = holding.get('lots', 0)
                                    break
                            break
        
        # 排序：按調整次數
        hot_stocks = [
            {
                'stock_code': code,
                'stock_name': data['name'],
                'total_adjustments': data['up_count'] + data['down_count'],
                'net_change': round(data['net_change'], 2),
                'etf_details': data['etf_details']
            }
            for code, data in stock_changes.items()
        ]
        hot_stocks.sort(key=lambda x: x['total_adjustments'], reverse=True)
        hot_stocks = hot_stocks[:10]  # 取前 10 名
        
        # 3. 詳細變動列表
        detailed_changes = []
        for etf_code, changes in sorted(changes_dict.items()):
            etf_name = etf_info_dict.get(etf_code, etf_code)
            
            # 分類變動
            added = [c for c in changes if c.change_type == 'ADDED']
            removed = [c for c in changes if c.change_type == 'REMOVED']
            modified = [c for c in changes if c.change_type not in ['ADDED', 'REMOVED']]
            
            etf_changes = {
                'etf_code': etf_code,
                'etf_name': etf_name,
                'total_changes': len(changes),
                'added': [
                    {
                        'stock_code': c.stock_code,
                        'stock_name': c.stock_name,
                        'lots': round(c.new_lots, 2)
                    }
                    for c in added
                ],
                'removed': [
                    {
                        'stock_code': c.stock_code,
                        'stock_name': c.stock_name,
                        'lots': round(c.old_lots, 2)
                    }
                    for c in removed
                ],
                'modified': [
                    {
                        'stock_code': c.stock_code,
                        'stock_name': c.stock_name,
                        'old_lots': round(c.old_lots, 2),
                        'new_lots': round(c.new_lots, 2),
                        'diff': round(c.lots_diff, 2),
                        'direction': 'up' if c.lots_diff > 0 else 'down'
                    }
                    for c in modified
                ]
            }
            detailed_changes.append(etf_changes)
        
        return {
            'date': date,
            'update_time': (datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S'),  # 台北时间 (UTC+8)
            'summary': {
                'total_etfs': len(changes_dict),
                'total_changes': total_changes
            },
            'change_distribution': change_distribution,
            'hot_stocks': hot_stocks,
            'detailed_changes': detailed_changes,
            'etf_holdings': etf_holdings or []
        }
    
    def generate_daily_report(
        self, 
        changes_dict: Dict[str, List[HoldingChange]], 
        date: str,
        etf_info_dict: Dict[str, str],
        etf_holdings: List[dict] = None
    ) -> Path:
        """
        生成每日報告 HTML 檔案
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            etf_info_dict: ETF代碼 -> ETF名稱的字典
            etf_holdings: ETF 持股明細列表（可選）
            
        Returns:
            Path: 生成的 HTML 檔案路徑
        """
        # 生成 JSON 資料
        data = self.generate_dashboard_data(changes_dict, date, etf_info_dict, etf_holdings)
        
        # 儲存 JSON 資料檔
        json_file = self.output_dir / f"data_{date}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 生成 HTML 報告
        html_file = self.output_dir / f"report_{date}.html"
        html_content = self._generate_report_html(data)
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return html_file
    
    def _generate_report_html(self, data: dict) -> str:
        """生成報告 HTML 內容"""
        date = data['date']
        summary = data['summary']
        
        # 生成 ETF 持股總覽 HTML
        etf_holdings_html = self._generate_etf_holdings_html(data.get('etf_holdings', []))
        
        html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ETF 持股變動報告 - {date}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }}
        
        .header-content {{
            flex: 1;
        }}
        
        .header h1 {{
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        
        .header .date {{
            color: #666;
            font-size: 1.2em;
        }}
        
        .btn-home {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 24px;
            border-radius: 10px;
            text-decoration: none;
            font-weight: bold;
            font-size: 1em;
            transition: transform 0.2s, box-shadow 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}
        
        .btn-home:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        .stat-card {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            text-align: center;
        }}
        
        .stat-card .number {{
            font-size: 3em;
            font-weight: bold;
            color: #667eea;
        }}
        
        .stat-card .label {{
            color: #666;
            font-size: 1.1em;
            margin-top: 10px;
        }}
        
        /* ETF 持股總覽區塊 */
        .holdings-section {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }}
        
        .holdings-section h2 {{
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.8em;
        }}
        
        .etf-holdings-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }}
        
        .etf-holdings-card {{
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            overflow: hidden;
        }}
        
        .etf-holdings-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s;
        }}
        
        .etf-holdings-header:hover {{
            background: linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%);
        }}
        
        .etf-holdings-header h4 {{
            margin: 0;
            font-size: 1.1em;
        }}
        
        .etf-holdings-header .toggle-icon {{
            font-size: 1.2em;
            transition: transform 0.3s;
        }}
        
        .etf-holdings-header.expanded .toggle-icon {{
            transform: rotate(180deg);
        }}
        
        .etf-holdings-content {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
            background: #f9fafb;
        }}
        
        .etf-holdings-content.expanded {{
            max-height: 500px;
            overflow-y: auto;
        }}
        
        .holdings-list {{
            padding: 15px;
        }}
        
        .holdings-list table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9em;
        }}
        
        .holdings-list th {{
            background: #e5e7eb;
            padding: 8px 10px;
            text-align: left;
            border-bottom: 1px solid #d1d5db;
        }}
        
        .holdings-list td {{
            padding: 6px 10px;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        .chart-card {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        
        .chart-card h2 {{
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.5em;
        }}
        
        .details-section {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        
        .details-section h2 {{
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.8em;
        }}
        
        /* 可摺疊的 ETF 卡片 */
        .etf-card {{
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            margin-bottom: 20px;
            overflow: hidden;
        }}
        
        .etf-card-header {{
            background: #f5f5f5;
            padding: 15px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s;
        }}
        
        .etf-card-header:hover {{
            background: #e8e8e8;
        }}
        
        .etf-card-header h3 {{
            color: #764ba2;
            margin: 0;
            font-size: 1.1em;
        }}
        
        .etf-card-header .toggle-icon {{
            font-size: 1.2em;
            transition: transform 0.3s;
            color: #764ba2;
        }}
        
        .etf-card-header.expanded .toggle-icon {{
            transform: rotate(180deg);
        }}
        
        .etf-card-content {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
            padding: 0 20px;
        }}
        
        .etf-card-content.expanded {{
            max-height: 2000px;
            padding: 20px;
        }}
        
        .changes-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        
        .changes-table th {{
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #ddd;
        }}
        
        .changes-table td {{
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
        }}
        
        /* 顏色調整：紅色=增加，綠色=減少（台股慣例）*/
        .up {{
            color: #ef4444;
            font-weight: bold;
        }}
        
        .down {{
            color: #10b981;
            font-weight: bold;
        }}
        
        .badge {{
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }}
        
        /* 新增成分股：紅色 */
        .badge-add {{
            background: #fee2e2;
            color: #991b1b;
        }}
        
        /* 移除成分股：綠色 */
        .badge-remove {{
            background: #d1fae5;
            color: #065f46;
        }}
        
        /* 熱門股票可展開項目 */
        .hot-stock-item {{
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            margin-bottom: 15px;
            overflow: hidden;
        }}
        
        .hot-stock-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s;
        }}
        
        .hot-stock-header:hover {{
            background: linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%);
        }}
        
        .hot-stock-info {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            align-items: center;
        }}
        
        .hot-stock-rank {{
            font-size: 1.3em;
            font-weight: bold;
            margin-right: 5px;
        }}
        
        .hot-stock-name {{
            font-size: 1.1em;
            font-weight: bold;
        }}
        
        .hot-stock-stats {{
            display: flex;
            gap: 15px;
            font-size: 0.95em;
        }}
        
        .hot-stock-content {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
            background: #f9fafb;
        }}
        
        .hot-stock-content.expanded {{
            max-height: 600px;
            overflow-y: auto;
        }}
        
        .etf-adjustments-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        
        .etf-adjustments-table th {{
            background: #e5e7eb;
            padding: 10px;
            text-align: left;
            border-bottom: 2px solid #d1d5db;
            font-weight: 600;
        }}
        
        .etf-adjustments-table td {{
            padding: 8px 10px;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        @media (max-width: 768px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
            
            .header {{
                flex-direction: column;
                text-align: center;
            }}
            
            .header h1 {{
                font-size: 1.8em;
            }}
            
            .etf-holdings-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <h1>📊 ETF 持股變動追蹤系統</h1>
                <div class="date">報告日期：{date} | 更新時間：{data['update_time']} (台北時間)</div>
            </div>
            <a href="index.html" class="btn-home">🏠 回到主頁</a>
        </div>
        
        {etf_holdings_html}
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="number">{summary['total_etfs']}</div>
                <div class="label">檔 ETF 有變動</div>
            </div>
            <div class="stat-card">
                <div class="number">{summary['total_changes']}</div>
                <div class="label">筆持股調整</div>
            </div>
        </div>
        
        <div class="charts-grid">
            <div class="chart-card">
                <h2>📈 變動分布</h2>
                <canvas id="distributionChart"></canvas>
            </div>
            <div class="chart-card">
                <h2>🔥 熱門調整股票 TOP 10</h2>
                <div id="hotStocksList"></div>
            </div>
        </div>
        
        <div class="details-section">
            <h2>📋 詳細變動明細</h2>
            {self._generate_details_html(data['detailed_changes'])}
        </div>
    </div>
    
    <script>
        const data = {json.dumps(data, ensure_ascii=False)};
        
        // 摺疊功能
        function toggleCard(header) {{
            header.classList.toggle('expanded');
            const content = header.nextElementSibling;
            content.classList.toggle('expanded');
        }}
        
        // 綁定所有摺疊卡片的點擊事件
        document.querySelectorAll('.etf-card-header, .etf-holdings-header').forEach(header => {{
            header.addEventListener('click', () => toggleCard(header));
        }});
        
        // 變動分布圓餅圖
        const distributionCtx = document.getElementById('distributionChart').getContext('2d');
        new Chart(distributionCtx, {{
            type: 'pie',
            data: {{
                labels: data.change_distribution.map(d => d.etf_code + ' ' + d.etf_name),
                datasets: [{{
                    data: data.change_distribution.map(d => d.count),
                    backgroundColor: [
                        '#667eea', '#764ba2', '#f093fb', '#4facfe',
                        '#43e97b', '#fa709a', '#fee140', '#30cfd0'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }}
                }}
            }}
        }});
        
        // 生成熱門股票列表
        function renderHotStocks() {{
            const container = document.getElementById('hotStocksList');
            let html = '';
            
            data.hot_stocks.forEach((stock, index) => {{
                html += `
                    <div class="hot-stock-item">
                        <div class="hot-stock-header" onclick="toggleHotStock(this)">
                            <div class="hot-stock-info">
                                <span class="hot-stock-rank">#${{index + 1}}</span>
                                <span class="hot-stock-name">${{stock.stock_code}} ${{stock.stock_name}}</span>
                                <div class="hot-stock-stats">
                                    <span>📊 ${{stock.total_adjustments}} 次調整</span>
                                    <span>合計: ${{stock.net_change > 0 ? '+' : ''}}${{stock.net_change}} 張</span>
                                </div>
                            </div>
                            <span class="toggle-icon">▼</span>
                        </div>
                        <div class="hot-stock-content">
                            <table class="etf-adjustments-table">
                                <thead>
                                    <tr>
                                        <th>ETF代碼</th>
                                        <th>ETF名稱</th>
                                        <th>調整</th>
                                        <th>持股張數</th>
                                        <th>權重</th>
                                    </tr>
                                </thead>
                                <tbody>
                `;
                
                // 添加 ETF 調整詳情
                if (stock.etf_details && stock.etf_details.length > 0) {{
                    stock.etf_details.forEach(detail => {{
                        const adjClass = detail.adjustment > 0 ? 'up' : 'down';
                        const adjArrow = detail.adjustment > 0 ? '▲' : '▼';
                        const adjSign = detail.adjustment > 0 ? '+' : '';
                        const weight = detail.weight ? `${{detail.weight.toFixed(2)}}%` : '-';
                        const lots = detail.lots ? `${{detail.lots.toLocaleString()}} 張` : '-';
                        
                        html += `
                            <tr>
                                <td>${{detail.etf_code}}</td>
                                <td>${{detail.etf_name}}</td>
                                <td class="${{adjClass}}">${{adjArrow}} ${{adjSign}}${{detail.adjustment}} 張</td>
                                <td>${{lots}}</td>
                                <td>${{weight}}</td>
                            </tr>
                        `;
                    }});
                }} else {{
                    html += '<tr><td colspan="5">無詳細資訊</td></tr>';
                }}
                
                html += `
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
            }});
            
            container.innerHTML = html;
        }}
        
        // 切換展開狀態
        function toggleHotStock(header) {{
            header.classList.toggle('expanded');
            const content = header.nextElementSibling;
            content.classList.toggle('expanded');
            const icon = header.querySelector('.toggle-icon');
            icon.style.transform = content.classList.contains('expanded') ? 'rotate(180deg)' : 'rotate(0deg)';
        }}
        
        // 執行渲染
        renderHotStocks();
    </script>
</body>
</html>"""
        return html
    
    def _generate_details_html(self, detailed_changes: List[dict]) -> str:
        """生成詳細變動的 HTML（使用可摺疊卡片）"""
        html_parts = []
        
        for etf_data in detailed_changes:
            # 生成卡片內容
            content_parts = []
            
            # 新增成分股
            if etf_data['added']:
                content_parts.append('<h4><span class="badge badge-add">➕ 新增成分股</span></h4>')
                content_parts.append('<table class="changes-table">')
                content_parts.append('<tr><th>股票代碼</th><th>股票名稱</th><th>持股張數</th></tr>')
                for stock in etf_data['added']:
                    content_parts.append(f"<tr><td>{stock['stock_code']}</td><td>{stock['stock_name']}</td><td>{stock['lots']:,.0f}張</td></tr>")
                content_parts.append('</table>')
            
            # 移除成分股
            if etf_data['removed']:
                content_parts.append('<h4><span class="badge badge-remove">➖ 移除成分股</span></h4>')
                content_parts.append('<table class="changes-table">')
                content_parts.append('<tr><th>股票代碼</th><th>股票名稱</th><th>原持股張數</th></tr>')
                for stock in etf_data['removed']:
                    content_parts.append(f"<tr><td>{stock['stock_code']}</td><td>{stock['stock_name']}</td><td>{stock['lots']:,.0f}張</td></tr>")
                content_parts.append('</table>')
            
            # 持股變動
            if etf_data['modified']:
                content_parts.append('<h4>📊 持股變動</h4>')
                content_parts.append('<table class="changes-table">')
                content_parts.append('<tr><th>股票代碼</th><th>股票名稱</th><th>原持股</th><th>新持股</th><th>增減</th></tr>')
                for stock in etf_data['modified']:
                    diff_class = 'up' if stock['direction'] == 'up' else 'down'
                    arrow = '▲' if stock['direction'] == 'up' else '▼'
                    sign = '+' if stock['diff'] > 0 else ''
                    content_parts.append(
                        f"<tr><td>{stock['stock_code']}</td><td>{stock['stock_name']}</td>"
                        f"<td>{stock['old_lots']:,.0f}張</td><td>{stock['new_lots']:,.0f}張</td>"
                        f"<td class='{diff_class}'>{arrow} {sign}{stock['diff']:,.0f}張</td></tr>"
                    )
                content_parts.append('</table>')
            
            content_html = '\n'.join(content_parts)
            
            # 生成可摺疊卡片
            html_parts.append(f"""
            <div class="etf-card">
                <div class="etf-card-header">
                    <h3>{etf_data['etf_code']} - {etf_data['etf_name']} ({etf_data['total_changes']} 筆變動)</h3>
                    <span class="toggle-icon">▼</span>
                </div>
                <div class="etf-card-content">
                    {content_html}
                </div>
            </div>
            """)
        
        return '\n'.join(html_parts)
    
    def _generate_etf_holdings_html(self, etf_holdings: List[dict]) -> str:
        """生成 ETF 持股總覽的 HTML"""
        if not etf_holdings:
            return ''
        
        cards_html = []
        for etf in etf_holdings:
            # 生成持股表格
            holdings_rows = []
            for holding in etf.get('holdings', []):  # 顯示所有持股
                weight_str = f"{holding.get('weight', 0):.2f}%" if holding.get('weight') else '-'
                lots_str = f"{holding.get('lots', 0):,.0f}張" if holding.get('lots') else '-'
                holdings_rows.append(
                    f"<tr><td>{holding.get('stock_code', '')}</td>"
                    f"<td>{holding.get('stock_name', '')}</td>"
                    f"<td>{weight_str}</td>"
                    f"<td>{lots_str}</td></tr>"
                )
            
            holdings_table = '\n'.join(holdings_rows) if holdings_rows else '<tr><td colspan="4">無持股資料</td></tr>'
            total_count = len(etf.get('holdings', []))

            
            cards_html.append(f"""
            <div class="etf-holdings-card">
                <div class="etf-holdings-header">
                    <h4>{etf.get('etf_code', '')} {etf.get('etf_name', '')} ({total_count} 檔成分股)</h4>
                    <span class="toggle-icon">▼</span>
                </div>
                <div class="etf-holdings-content">
                    <div class="holdings-list">
                        <table>
                            <tr><th>代碼</th><th>名稱</th><th>權重</th><th>持股</th></tr>
                            {holdings_table}
                        </table>
                    </div>
                </div>
            </div>
            """)
        
        return f"""
        <div class="holdings-section">
            <h2>📋 追蹤 ETF 持股總覽</h2>
            <div class="etf-holdings-grid">
                {''.join(cards_html)}
            </div>
        </div>
        """

