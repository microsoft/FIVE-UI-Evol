// Table sorting functionality adapted from lvbench
// Source: https://github.com/lvbench/lvbench.github.io

(function() {
    'use strict';
    
    // 存储每列的排序状态: 'asc', 'desc'
    const columnSortStates = new Map();
    
    function numberSort(a, b, ascending = false) {
        // 处理 "-" 字符串和其他非数值情况
        const aTrimmed = a.trim();
        const bTrimmed = b.trim();
        
        // 检查是否为"-"或空值
        const aIsEmpty = aTrimmed === "-" || aTrimmed === "" || aTrimmed === "—" || aTrimmed === "N/A";
        const bIsEmpty = bTrimmed === "-" || bTrimmed === "" || bTrimmed === "—" || bTrimmed === "N/A";
        
        // 如果都是空值
        if (aIsEmpty && bIsEmpty) return 0;
        
        // 空值总是排在最后（降序时排在最后，升序时排在最后）
        if (aIsEmpty) return 1;
        if (bIsEmpty) return -1;
        
        // 提取数值
        const aNum = parseFloat(aTrimmed.replace(/[^\d.-]/g, ''));
        const bNum = parseFloat(bTrimmed.replace(/[^\d.-]/g, ''));
        
        // Debug log (limited output)
        if (window.debugCount === undefined) window.debugCount = 0;
        if (window.debugCount < 3) {
            console.log('Comparing numbers:', a, '→', aNum, 'vs', b, '→', bNum, 'ascending:', ascending);
            window.debugCount++;
        }
        
        // 如果提取后仍然不是数值，也排到最后
        if (isNaN(aNum) && isNaN(bNum)) return 0;
        if (isNaN(aNum)) return 1;
        if (isNaN(bNum)) return -1;
        
        return ascending ? aNum - bNum : bNum - aNum;
    }
    
    function dateSort(a, b, ascending = false) {
        // Handle date format like "2025-1-15"
        const parseDate = (dateStr) => {
            const parts = dateStr.split('-');
            if (parts.length === 3) {
                return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
            }
            return new Date(dateStr);
        };
        
        const aDate = parseDate(a);
        const bDate = parseDate(b);
        
        if (isNaN(aDate.getTime()) && isNaN(bDate.getTime())) return 0;
        if (isNaN(aDate.getTime())) return 1;
        if (isNaN(bDate.getTime())) return -1;
        
        return ascending ? aDate - bDate : bDate - aDate;
    }
    
    function textSort(a, b, ascending = true) {
        return ascending ? a.localeCompare(b) : b.localeCompare(a);
    }
    
    function sortTable(table, columnIndex, sortType, sortState) {
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        
        if (rows.length === 0) return;
        
        const ascending = (sortState === 'asc');
        
        const sortedRows = rows.sort((rowA, rowB) => {
            const cellA = rowA.cells[columnIndex];
            const cellB = rowB.cells[columnIndex];
            
            if (!cellA || !cellB) return 0;
            
            let valueA = cellA.textContent.trim();
            let valueB = cellB.textContent.trim();
            
            // Handle special cases for model names - extract just the model name
            if (columnIndex === 1) { // Model column
                const divA = cellA.querySelector('.model-name');
                const divB = cellB.querySelector('.model-name');
                if (divA) valueA = divA.textContent.trim();
                if (divB) valueB = divB.textContent.trim();
            }
            
            // Handle date column
            if (sortType === 'date') {
                return dateSort(valueA, valueB, ascending);
            }
            
            // Handle number columns
            if (sortType === 'number') {
                return numberSort(valueA, valueB, ascending);
            }
            
            // Text sorting
            return textSort(valueA, valueB, ascending);
        });
        
        // Update row rankings
        sortedRows.forEach((row, index) => {
            if (row.cells[0]) {
                row.cells[0].textContent = index + 1;
            }
        });
        
        // Re-append sorted rows
        sortedRows.forEach(row => tbody.appendChild(row));
        
        // Update header indicators - 这里不更新，在点击事件中处理
    }
    
    function initSortableTable() {
        const tables = document.querySelectorAll('.js-sort-table');
        
        tables.forEach(table => {
            const headers = table.querySelectorAll('th');
            
            headers.forEach((header, index) => {
                if (header.classList.contains('no-sort')) {
                    return;
                }
                
                // 跳过分组标题（colspan > 1的表头）
                const colspan = parseInt(header.getAttribute('colspan')) || 1;
                if (colspan > 1) {
                    return; // 分组标题不应该排序
                }
                
                // 初始化排序状态
                const stateKey = `table-${Array.from(tables).indexOf(table)}-col-${index}`;
                if (!columnSortStates.has(stateKey)) {
                    columnSortStates.set(stateKey, 'desc'); // 默认降序
                }
                
                header.style.cursor = 'pointer';
                header.addEventListener('click', () => {
                    let sortType = 'text';
                    let actualColumnIndex = index;
                    
                    // Determine sort type based on header content and position
                    const headerText = header.textContent.toLowerCase().trim();
                    
                    // 通过表头文本直接映射到数据索引，避免复杂表头索引问题
                    const isCombinedView = table.querySelector('th')?.textContent.includes('ScreenSpot-Pro') || 
                                          document.querySelector('tbody')?.children[0]?.children.length === 13;
                    
                    if (isCombinedView) {
                        // Combined表格的文本映射（表头文本 → 实际表格列索引）
                        let combinedTextMap = {
                            'mobile': 5,        // Mobile → 表格第5列
                            'web': 6,           // Web → 表格第6列
                            'desktop': 7,       // Desktop → 表格第7列
                            'explicit': 9,      // Explicit → 表格第9列
                            'implicit': 10,     // Implicit → 表格第10列
                            'screenspot-pro': 12, // ScreenSpot-Pro → 表格第12列
                            'params': 2,        // Params → 表格第2列
                            'date': 3,          // Date → 表格第3列
                            'overall': 4        // Overall → 表格第4列
                        };
                         
                         // 特殊处理两个Avg.列 - 通过查找前一个兄弟元素来区分
                         if (headerText === 'avg.') {
                             // 查找前面的列来判断是哪个Avg
                             let prevHeader = header.previousElementSibling;
                             let foundScreenSpotContext = false;
                             let foundUIBenchContext = false;
                             
                             // 向前查找，看前面的列属于哪个分组
                             while (prevHeader) {
                                 const prevText = prevHeader.textContent.toLowerCase().trim();
                                 if (prevText === 'desktop' || prevText === 'mobile' || prevText === 'web') {
                                     foundScreenSpotContext = true;
                                     break;
                                 }
                                 if (prevText === 'explicit' || prevText === 'implicit') {
                                     foundUIBenchContext = true;
                                     break;
                                 }
                                 prevHeader = prevHeader.previousElementSibling;
                             }
                             
                             if (foundScreenSpotContext) {
                                 combinedTextMap['avg.'] = 8; // ScreenSpot Avg → 表格第8列
                             } else if (foundUIBenchContext) {
                                 combinedTextMap['avg.'] = 11; // UI-I2E-Bench Avg → 表格第11列
                             }
                         }
                        
                        if (combinedTextMap.hasOwnProperty(headerText)) {
                            actualColumnIndex = combinedTextMap[headerText];
                        }
                    } else {
                        // UI-I2E-Bench表格的文本映射（表头文本 → 实际表格列索引）
                        const singleTextMap = {
                            'web': 5,           // Web → 表格第5列
                            'desktop': 6,       // Desktop → 表格第6列
                            'mobile': 7,        // Mobile → 表格第7列
                            'button': 8,        // Button → 表格第8列
                            'icon': 9,          // Icon → 表格第9列
                            'dropdown': 10,     // Dropdown → 表格第10列
                            'input': 11,        // Input → 表格第11列
                            'toggle': 12,       // Toggle → 表格第12列
                            'explicit': 13,     // Explicit → 表格第13列
                            'implicit': 14,     // Implicit → 表格第14列
                            'params': 2,        // Params → 表格第2列
                            'date': 3,          // Date → 表格第3列
                            'overall': 4        // Overall → 表格第4列
                        };
                        
                        if (singleTextMap.hasOwnProperty(headerText)) {
                            actualColumnIndex = singleTextMap[headerText];
                        }
                    }
                    
                    // 确定排序类型
                    if (headerText.includes('date')) {
                        sortType = 'date';
                    } else if (
                        headerText.includes('%') || 
                        headerText.includes('overall') || 
                        headerText.includes('avg') || 
                        headerText.includes('score') ||
                        headerText.includes('mobile') ||
                        headerText.includes('web') ||
                        headerText.includes('desktop') ||
                        headerText.includes('button') ||
                        headerText.includes('icon') ||
                        headerText.includes('dropdown') ||
                        headerText.includes('input') ||
                        headerText.includes('toggle') ||
                        headerText.includes('explicit') ||
                        headerText.includes('implicit') ||
                        headerText.includes('screenspot') ||
                        /\b(er|eu|kir|tg|rea|sum)\b/.test(headerText)
                    ) {
                        sortType = 'number';
                    } else if (headerText.includes('params')) {
                        sortType = 'text'; // Handle params like "72B", "7B" as text
                    }
                    
                    // Debug log for sort type
                    console.log('Column:', headerText, 'Sort type:', sortType, 'Header index:', index, 'Data index:', actualColumnIndex);
                    
                    // 重置调试计数器
                    window.debugCount = 0;
                    
                    // 清除其他列的排序状态显示
                    headers.forEach((h, i) => {
                        if (i !== index) {
                            h.classList.remove('sorted-asc', 'sorted-desc');
                        }
                    });
                    
                    // 切换当前列的排序状态（升序 ↔ 降序）
                    const currentState = columnSortStates.get(stateKey);
                    const nextState = (currentState === 'asc') ? 'desc' : 'asc';
                    
                    columnSortStates.set(stateKey, nextState);
                    sortTable(table, actualColumnIndex, sortType, nextState);
                    
                    // 更新当前表头的排序指示器
                    header.classList.remove('sorted-asc', 'sorted-desc');
                    if (nextState === 'asc') {
                        header.classList.add('sorted-asc');
                    } else if (nextState === 'desc') {
                        header.classList.add('sorted-desc');
                    }
                });
            });
        });
    }
    
    // Make initSortableTable available globally for re-initialization
    window.initSortableTable = initSortableTable;
    
    // Initialize when DOM is loaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSortableTable);
    } else {
        initSortableTable();
    }
})(); 