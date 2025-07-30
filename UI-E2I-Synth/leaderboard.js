document.addEventListener("DOMContentLoaded", function () {
    let combined = true;

    renderTable(combined);

    document.getElementById("btn_single").addEventListener("click", function () {
        combined = false;  
        renderTable(combined); 
    });

    document.getElementById("btn_combined").addEventListener("click", function () {
        combined = true;  
        renderTable(combined);  
    });

    function findBestScore(data, columnIndex) {
        let best = -1;
        data.forEach(row => {
            const value = parseFloat(row.values[columnIndex]);
            if (!isNaN(value) && value > best) {
                best = value;
            }
        });
        return best;
    }

    function formatModelName(model) {
        // 简化的模型名称和组织映射
        const modelInfo = {
            "InternVL2-4B": { name: "InternVL2-4B", org: "Shanghai AI Laboratory", link: "https://huggingface.co/OpenGVLab/InternVL2-4B" },
            "Qwen2-VL-7B": { name: "Qwen2-VL-7B", org: "Alibaba", link: "https://huggingface.co/Qwen/Qwen2-VL-7B-Instruct" },
            "OmniParser": { name: "OmniParser", org: "Microsoft", link: "https://github.com/microsoft/OmniParser" },
            "Seeclick": { name: "Seeclick", org: "Shanghai AI Laboratory", link: "https://github.com/njucckevin/SeeClick" },
            "UGround-7B": { name: "UGround-7B", org: "The Ohio State University", link: "https://github.com/SJTU-LIT/UGround" },
            "Uground-7B": { name: "Uground-7B", org: "The Ohio State University", link: "https://github.com/SJTU-LIT/UGround" },
            "ShowUI-2B": { name: "ShowUI-2B", org: "ShowLab", link: "https://github.com/showlab/ShowUI" },
            "OS-Atlas-4B": { name: "OS-Atlas-4B", org: "Shanghai AI Laboratory", link: "https://github.com/OS-Copilot/OS-Atlas" },
            "OS-Atlas-7B": { name: "OS-Atlas-7B", org: "Shanghai AI Laboratory", link: "https://github.com/OS-Copilot/OS-Atlas" },
            "UI-I2E-VLM-4B": { name: "UI-I2E-VLM-4B", org: "Microsoft", link: "#" },
            "UI-I2E-VLM-7B": { name: "UI-I2E-VLM-7B", org: "Microsoft", link: "#" },
            "Uground-V1-2B": { name: "Uground-V1-2B", org: "The Ohio State University", link: "https://github.com/SJTU-LIT/UGround" },
            "Uground-V1-7B": { name: "Uground-V1-7B", org: "The Ohio State University", link: "https://github.com/SJTU-LIT/UGround" },
            "Uground-V1-72B": { name: "Uground-V1-72B", org: "The Ohio State University", link: "https://github.com/SJTU-LIT/UGround" },
            "UI-TARS-2B": { name: "UI-TARS-2B", org: "ByteDance", link: "https://github.com/bytedance/UI-TARS" },
            "UI-TARS-7B": { name: "UI-TARS-7B", org: "ByteDance", link: "https://github.com/bytedance/UI-TARS" },
            "UI-TARS-72B": { name: "UI-TARS-72B", org: "ByteDance", link: "https://github.com/bytedance/UI-TARS" },
            "Aguvis-7B": { name: "Aguvis-7B", org: "University of Hong Kong", link: "https://github.com/THUDM/Aguvis" },
            "Qwen2.5-VL-3B": { name: "Qwen2.5-VL-3B", org: "Alibaba", link: "https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct" },
            "Qwen2.5-VL-7B": { name: "Qwen2.5-VL-7B", org: "Alibaba", link: "https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct" },
            "Qwen2.5-VL-72B": { name: "Qwen2.5-VL-72B", org: "Alibaba", link: "https://huggingface.co/Qwen/Qwen2.5-VL-72B-Instruct" },
            "OmniParser-V2": { name: "OmniParser-V2", org: "Microsoft", link: "https://github.com/microsoft/OmniParser" },
            "InfiGUI-R1": { name: "InfiGUI-R1", org: "Reallm Labs", link: "https://github.com/deepseek-ai/InfiGUI" },
            "UI-R1": { name: "UI-R1", org: "vivo AI Lab", link: "https://github.com/deepseek-ai/DeepSeek-R1" },
            "UI-TARS-1.5-7B": { name: "UI-TARS-1.5-7B", org: "ByteDance", link: "https://github.com/bytedance/UI-TARS" }
        };

        const info = modelInfo[model] || { name: model, org: "Unknown", link: "#" };
        return `<div class="model-name">${info.name}</div><div class="model-org">${info.org}</div>`;
    }

    function generateModelParams(model) {
        // 简化的参数映射
        if (model.includes("72B")) return "72B";
        if (model.includes("7B")) return "7B";
        if (model.includes("4B")) return "4B";
        if (model.includes("3B")) return "3B";
        if (model.includes("2B")) return "2B";
        // 特殊模型的参数映射
        if (model === "InfiGUI-R1" || model === "UI-R1") return "3B";
        return "-";
    }

    function generateDate(model) {
        // 模型发布日期映射
        const dates = {
            "Aguvis-7B": "2024.12",
            "InfiGUI-R1": "2025.04",
            "InternVL2-4B": "2024.07",
            "OmniParser": "2024.08",
            "OmniParser-V2": "2025.02",
            "OS-Atlas-4B": "2024.10",
            "OS-Atlas-7B": "2024.10",
            "Qwen2-VL-7B": "2024.09",
            "Qwen2.5-VL-3B": "2025.02",
            "Qwen2.5-VL-7B": "2025.02",
            "Qwen2.5-VL-72B": "2025.02",
            "Seeclick": "2024.01",
            "ShowUI-2B": "2024.11",
            "UGround-7B": "2024.10",
            "Uground-7B": "2024.10",
            "Uground-V1-2B": "2024.10",
            "Uground-V1-7B": "2024.10",
            "Uground-V1-72B": "2024.10",
            "UI-I2E-VLM-4B": "2025.04",
            "UI-I2E-VLM-7B": "2025.04",
            "UI-R1": "2025.03",
            "UI-TARS-2B": "2025.01",
            "UI-TARS-7B": "2025.01",
            "UI-TARS-72B": "2025.01",
            "UI-TARS-1.5-7B": "2025.04"
        };
        return dates[model] || "2024.11";
    }

    function renderTable(isCombined) {
        let tableHtml = "";
        
        if (isCombined) {
            const combinedTableData = [
                { model: "InternVL2-4B", avg: 1.8, values: [7.2, 0.5, 4.5, 4.2, 1.4, 0.5, 0.9, 0.3] },
                { model: "Qwen2-VL-7B", avg: 31.0, values: [51.3, 27.7, 49.1, 42.6, 53.8, 45.6, 48.7, 1.6] },
                { model: "OmniParser", avg: 45.1, values: [78.5, 63.9, 79.7, 73.9, 54.3, 52.4, 53.1, 8.3] },
                { model: "Seeclick", avg: 27.8, values: [66.1, 44.7, 54.5, 55.8, 37.1, 19.9, 26.4, 1.1] },
                { model: "UGround-7B", avg: 48.3, values: [72.5, 75.7, 74.6, 74.1, 65.8, 47.1, 54.2, 16.5] },
                { model: "ShowUI-2B", avg: 42.0, values: [84.6, 73.2, 69.9, 76.8, 51.3, 35.6, 41.5, 7.7] },
                { model: "OS-Atlas-4B", avg: 39.4, values: [73.3, 73.4, 61.1, 70.1, 51.5, 39.9, 44.3, 3.7] },
                { model: "OS-Atlas-7B", avg: 53.3, values: [83.8, 83.1, 79.7, 82.5, 63.2, 55.8, 58.6, 18.9] },
                { model: "UI-I2E-VLM-4B", avg: 45.3, values: [70.3, 70.9, 70.1, 70.4, 61.9, 48.3, 53.4, 12.2] },
                { model: "UI-I2E-VLM-7B", avg: 58.5, values: [86.5, 78.0, 82.6, 82.5, 72.0, 67.9, 69.5, 23.6] },
                { model: "Uground-V1-2B", avg: 54.3, values: [81.5, 75.4, 79.1, 78.8, 72.9, 47.9, 57.4, 26.6]},
                { model: "Uground-V1-7B", avg: 62.8, values: [87.0, 87.6, 86.5, 87.1, 81.3, 63.6, 70.3, 31.1]},
                { model: "Uground-V1-72B", avg: 66.8, values: [89.2, 89.2, 91.0, 89.7, 84.5, 71.3, 76.3, 34.3]},
                { model: "UI-TARS-2B", avg: 57.3, values: [85.0, 79.8, 81.4, 82.3, 74.1, 54.5, 62.0, 27.7]},
                { model: "UI-TARS-7B", avg: 62.2, values: [90.3, 86.9, 91.6, 89.5, 71.4, 55.3, 61.4, 35.7]},
                { model: "UI-TARS-72B", avg: 66.7, values: [89.2, 87.0, 89.2, 88.4, 80.9, 69.4, 73.7, 38.1]},
                { model: "Aguvis-7B", avg: 40.4, values: [87.4, 82.1, 82.6, 84.4, 61.1, 48.4, 53.2, 22.9]},
                { model: "Qwen2.5-VL-3B", avg: 41.3, values: ["-", "-", "-", 55.5, 51.4, 35.8, 41.7, 23.9]},
                { model: "Qwen2.5-VL-7B", avg: 55.8, values: ["-", "-", "-", 84.7, 58.4, 51.0, 53.8, 29.0]},
                { model: "Qwen2.5-VL-72B", avg: 60.7, values: ["-", "-", "-", 87.1, 49.6, 52.5, 51.4, 43.6]},
                { model: "OmniParser-V2", avg: 55.5, values: [75.7, 66.3, 74.1, 72.0, 57.0, 53.5, 54.8, 39.6]},
                { model: "InfiGUI-R1", avg: 62.3, values: [89.9, 85.0, 87.1, 87.5, 78.7, 64.2, 69.7, 29.6]},
                { model: "UI-R1", avg: 51.6, values: ["-", 79.6, 77.2, 78.6, 67.9, 52.8, 58.5, 17.8]},
                { model: "UI-TARS-1.5-7B", avg: 67.8, values: [88.5, 87.6, 88.3, 88.1, 81.3, 68.2, 73.2, 42.2]}
            ];

            combinedTableData.sort((a, b) => b.avg - a.avg);

            // 找到最佳分数用于高亮
            const bestOverall = Math.max(...combinedTableData.map(row => row.avg));

            tableHtml = `
                <thead>
                    <tr>
                        <th rowspan="2" class="no-sort"><strong>#</strong></th>
                        <th rowspan="2" class="no-sort"><strong>Model</strong></th>
                        <th rowspan="2"><strong>Params</strong></th>
                        <th rowspan="2"><strong>Date</strong></th>
                        <th rowspan="2"><strong>Overall (%)</strong></th>
                        <th colspan="4">ScreenSpot</th>
                        <th colspan="3">UI-I2E-Bench</th>
                        <th rowspan="2"><strong>ScreenSpot-Pro</strong></th>
                    </tr>
                    <tr>
                        <th>Mobile</th>
                        <th>Web</th>
                        <th>Desktop</th>
                        <th>Avg.</th>
                        <th>Explicit</th>
                        <th>Implicit</th>
                        <th>Avg.</th>
                    </tr>
                </thead>
                <tbody>
                    ${combinedTableData.map((row, index) => `
                        <tr>
                            <td>${index + 1}</td>
                            <td style="text-align: left;">${formatModelName(row.model)}</td>
                            <td>${generateModelParams(row.model)}</td>
                            <td><strong style="color: #22a56e;">${generateDate(row.model)}</strong></td>
                            <td ${row.avg === bestOverall ? 'class="best-score"' : ''}><b>${row.avg}</b></td>
                            ${row.values.map(value => `<td>${value}</td>`).join('')}
                        </tr>
                    `).join('')}
                </tbody>
                <tfoot>
                    <tr>
                        <td colspan="13" style="text-align:center;">Overall = arithmetic mean of average accuracy across three benchmarks.</td>
                    </tr>
                </tfoot>
            `;
        } else {
            const singleTableData = [
                { model: "OmniParser", avg: 53.1, values: [30.8, 45.5, 67.6, 68.4, 60.5, 65.9, 58.9, 26.9, 54.3, 52.4] },
                { model: "Seeclick", avg: 26.4, values: [18.2, 15.8, 37.2, 31.6, 26.2, 22.5, 29.6, 22.1, 37.1, 19.9] },
                { model: "Uground-7B", avg: 54.2, values: [53.0, 44.3, 61.8, 57.3, 49.7, 76.4, 64.2, 37.0, 65.8, 47.1] },
                { model: "ShowUI-2B", avg: 41.5, values: [29.6, 30.4, 53.9, 52.0, 44.1, 51.1, 52.8, 18.9, 51.3, 35.6] },
                { model: "OS-Atlas-4B", avg: 44.3, values: [54.6, 19.9, 58.6, 43.5, 44.1, 46.6, 46.3, 42.2, 51.5, 39.9] },
                { model: "OS-Atlas-7B", avg: 58.6, values: [52.2, 48.9, 68.1, 69.1, 58.7, 80.3, 70.1, 32.3, 63.2, 55.8] },
                { model: "UI-I2E-VLM-4B", avg: 53.4, values: [60.9, 38.9, 61.4, 54.3, 50.0, 61.2, 68.6, 39.0, 61.9, 48.3] },
                { model: "UI-I2E-VLM-7B", avg: 69.5, values: [62.1, 64.0, 76.2, 77.0, 68.2, 84.8, 86.2, 44.4, 72.0, 67.9] },
                { model: "Uground-V1-2B", avg: 57.4, values: [66.4, 49.5, 59.9, 57.6, 50.7, 82.0, 64.8, 44.7, 72.9, 47.9]},
                { model: "Uground-V1-7B", avg: 70.3, values: [70.8, 65.7, 73.5, 72.9, 62.9, 83.7, 75.4, 63.5, 81.3, 63.6]},
                { model: "Uground-V1-72B", avg: 76.3, values: [74.7, 74.6, 78.2, 79.6, 75.5, 93.3, 74.5, 68.7, 84.5, 71.3]},
                { model: "UI-TARS-2B", avg: 62.0, values: [62.2, 54.0, 66.7, 59.1, 55.6, 82.6, 72.7, 50.1, 74.1, 54.5]},
                { model: "UI-TARS-7B", avg: 61.4, values: [56.5, 58.0, 65.7, 66.5, 63.3, 75.3, 60.4, 51.4, 71.4, 55.3]},
                { model: "UI-TARS-72B", avg: 73.7, values: [77.1, 69.8, 75.5, 78.8, 75.2, 80.9, 73.9, 66.0, 80.9, 69.4]},
                { model: "Aguvis-7B", avg: 53.2, values: [45.1, 47.6, 60.3, 60.2, 56.3, 74.2, 54.8, 35.7, 61.1, 48.4]},
                { model: "Qwen2.5-VL-3B", avg: 41.7, values: [39.9, 38.7, 44.5, 48.3, 46.9, 69.7, 29.0, 32.0, 51.4, 35.8]},
                { model: "Qwen2.5-VL-7B", avg: 53.8, values: [56.9, 41.6, 61.7, 59.5, 59.4, 74.7, 42.8, 46.2, 58.4, 51.0]},
                { model: "Qwen2.5-VL-72B", avg: 51.4, values: [49.0, 47.2, 55.3, 63.9, 64.0, 62.4, 35.5, 42.7, 49.6, 52.5]},
                { model: "OmniParser-V2", avg: 54.8, values: [40.7, 42.4, 69.4, 72.2, 61.6, 64.4, 60.9, 29.4, 57.0, 53.5]},
                { model: "InfiGUI-R1", avg: 69.7, values:[71.7, 57.2, 78.2, 71.6, 67.5, 82.6, 74.2, 60.4, 78.7, 64.2]},
                { model: "UI-R1", avg:58.5, values: [58.1, 46.2, 67.8, 61.7, 54.9, 70.8, 59.1, 53.1, 67.9, 52.8]},
                { model: "UI-TARS-1.5-7B", avg: 73.2, values: [79.5, 68.8, 74.1, 76.6, 71.7, 82.0, 75.3, 66.3, 81.3, 68.2]}
            ];

            singleTableData.sort((a, b) => b.avg - a.avg);

            // 找到最佳分数用于高亮
            const bestOverall = Math.max(...singleTableData.map(row => row.avg));

            tableHtml = `
                <thead>
                    <tr>
                        <th rowspan="2" class="no-sort"><strong>#</strong></th>
                        <th rowspan="2" class="no-sort"><strong>Model</strong></th>
                        <th rowspan="2"><strong>Params</strong></th>
                        <th rowspan="2"><strong>Date</strong></th>
                        <th rowspan="2"><strong>Overall (%)</strong></th>
                        <th colspan="3">Platform</th>
                        <th colspan="5">Element Type</th>
                        <th colspan="2">Implicitness</th>
                    </tr>
                    <tr>
                        <th>Web</th>
                        <th>Desktop</th>
                        <th>Mobile</th>
                        <th>Button</th>
                        <th>Icon</th>
                        <th>Dropdown</th>
                        <th>Input</th>
                        <th>Toggle</th>
                        <th>Explicit</th>
                        <th>Implicit</th>
                    </tr>
                </thead>
                <tbody>
                    ${singleTableData.map((row, index) => `
                        <tr>
                            <td>${index + 1}</td>
                            <td style="text-align: left;">${formatModelName(row.model)}</td>
                            <td>${generateModelParams(row.model)}</td>
                            <td><strong style="color: #22a56e;">${generateDate(row.model)}</strong></td>
                            <td ${row.avg === bestOverall ? 'class="best-score"' : ''}><b>${row.avg}</b></td>
                            ${row.values.map(value => `<td>${value}</td>`).join('')}
                        </tr>
                    `).join('')}
                </tbody>
            `;
        }
        document.getElementById("plused").innerHTML = tableHtml;
        
        // 重新初始化排序功能
        if (window.initSortableTable) {
            window.initSortableTable();
        } else {
            // 如果排序功能还没有加载，等待一下再尝试
            setTimeout(() => {
                if (window.initSortableTable) {
                    window.initSortableTable();
                }
            }, 100);
        }
    }
});