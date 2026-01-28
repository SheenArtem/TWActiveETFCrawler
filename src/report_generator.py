"""
報告生成器模組 - 生成 HTML 格式的視覺化報告
"""
from typing import Dict, List
from pathlib import Path
import json
from datetime import datetime
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
        etf_info_dict: Dict[str, str]
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
        stock_changes = {}  # stock_code -> {name, up_count, down_count, net_change}
        
        for etf_code, changes in changes_dict.items():
            for change in changes:
                if change.change_type in ['SHARES_UP', 'SHARES_DOWN']:
                    code = change.stock_code
                    if code not in stock_changes:
                        stock_changes[code] = {
                            'name': change.stock_name,
                            'up_count': 0,
                            'down_count': 0,
                            'net_change': 0
                        }
                    
                    if change.change_type == 'SHARES_UP':
                        stock_changes[code]['up_count'] += 1
                        stock_changes[code]['net_change'] += change.lots_diff
                    else:
                        stock_changes[code]['down_count'] += 1
                        stock_changes[code]['net_change'] += change.lots_diff
        
        # 排序：按調整次數
        hot_stocks = [
            {
                'stock_code': code,
                'stock_name': data['name'],
                'total_adjustments': data['up_count'] + data['down_count'],
                'net_change': round(data['net_change'], 2)
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
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'summary': {
                'total_etfs': len(changes_dict),
                'total_changes': total_changes
            },
            'change_distribution': change_distribution,
            'hot_stocks': hot_stocks,
            'detailed_changes': detailed_changes
        }
    
    def generate_daily_report(
        self, 
        changes_dict: Dict[str, List[HoldingChange]], 
        date: str,
        etf_info_dict: Dict[str, str]
    ) -> Path:
        """
        生成每日報告 HTML 檔案
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            etf_info_dict: ETF代碼 -> ETF名稱的字典
            
        Returns:
            Path: 生成的 HTML 檔案路徑
        """
        # 生成 JSON 資料
        data = self.generate_dashboard_data(changes_dict, date, etf_info_dict)
        
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
        
        .etf-card {{
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        
        .etf-card h3 {{
            color: #764ba2;
            margin-bottom: 15px;
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
        
        .up {{
            color: #10b981;
            font-weight: bold;
        }}
        
        .down {{
            color: #ef4444;
            font-weight: bold;
        }}
        
        .badge {{
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }}
        
        .badge-add {{
            background: #d1fae5;
            color: #065f46;
        }}
        
        .badge-remove {{
            background: #fee2e2;
            color: #991b1b;
        }}
        
        @media (max-width: 768px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
            
            .header h1 {{
                font-size: 1.8em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 ETF 持股變動追蹤系統</h1>
            <div class="date">報告日期：{date} | 更新時間：{data['update_time']}</div>
        </div>
        
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
                <canvas id="hotStocksChart"></canvas>
            </div>
        </div>
        
        <div class="details-section">
            <h2>📋 詳細變動明細</h2>
            {self._generate_details_html(data['detailed_changes'])}
        </div>
    </div>
    
    <script>
        const data = {json.dumps(data, ensure_ascii=False)};
        
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
        
        // 熱門股票長條圖
        const hotStocksCtx = document.getElementById('hotStocksChart').getContext('2d');
        new Chart(hotStocksCtx, {{
            type: 'bar',
            data: {{
                labels: data.hot_stocks.map(s => s.stock_code + ' ' + s.stock_name),
                datasets: [{{
                    label: '調整次數',
                    data: data.hot_stocks.map(s => s.total_adjustments),
                    backgroundColor: '#667eea'
                }}]
            }},
            options: {{
                responsive: true,
                indexAxis: 'y',
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }},
                scales: {{
                    x: {{
                        beginAtZero: true,
                        ticks: {{
                            stepSize: 1
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
        return html
    
    def _generate_details_html(self, detailed_changes: List[dict]) -> str:
        """生成詳細變動的 HTML"""
        html_parts = []
        
        for etf_data in detailed_changes:
            html_parts.append(f"""
            <div class="etf-card">
                <h3>{etf_data['etf_code']} - {etf_data['etf_name']} ({etf_data['total_changes']} 筆變動)</h3>
            """)
            
            # 新增成分股
            if etf_data['added']:
                html_parts.append('<h4><span class="badge badge-add">➕ 新增成分股</span></h4>')
                html_parts.append('<table class="changes-table">')
                html_parts.append('<tr><th>股票代碼</th><th>股票名稱</th><th>持股張數</th></tr>')
                for stock in etf_data['added']:
                    html_parts.append(f"<tr><td>{stock['stock_code']}</td><td>{stock['stock_name']}</td><td>{stock['lots']:,.0f}張</td></tr>")
                html_parts.append('</table>')
            
            # 移除成分股
            if etf_data['removed']:
                html_parts.append('<h4><span class="badge badge-remove">➖ 移除成分股</span></h4>')
                html_parts.append('<table class="changes-table">')
                html_parts.append('<tr><th>股票代碼</th><th>股票名稱</th><th>原持股張數</th></tr>')
                for stock in etf_data['removed']:
                    html_parts.append(f"<tr><td>{stock['stock_code']}</td><td>{stock['stock_name']}</td><td>{stock['lots']:,.0f}張</td></tr>")
                html_parts.append('</table>')
            
            # 持股變動
            if etf_data['modified']:
                html_parts.append('<h4>📊 持股變動</h4>')
                html_parts.append('<table class="changes-table">')
                html_parts.append('<tr><th>股票代碼</th><th>股票名稱</th><th>原持股</th><th>新持股</th><th>增減</th></tr>')
                for stock in etf_data['modified']:
                    diff_class = 'up' if stock['direction'] == 'up' else 'down'
                    arrow = '▲' if stock['direction'] == 'up' else '▼'
                    sign = '+' if stock['diff'] > 0 else ''
                    html_parts.append(
                        f"<tr><td>{stock['stock_code']}</td><td>{stock['stock_name']}</td>"
                        f"<td>{stock['old_lots']:,.0f}張</td><td>{stock['new_lots']:,.0f}張</td>"
                        f"<td class='{diff_class}'>{arrow} {sign}{stock['diff']:,.0f}張</td></tr>"
                    )
                html_parts.append('</table>')
            
            html_parts.append('</div>')
        
        return '\n'.join(html_parts)
