(function() {
    'use strict';

    // --- 검색 기능 ---
    var searchBox = document.getElementById('search-box');
    var searchCount = document.getElementById('search-count');
    var contentEl = document.getElementById('report-content');
    var debounceTimer = null;

    function clearHighlights() {
        var marks = contentEl.querySelectorAll('mark.search-highlight');
        for (var i = 0; i < marks.length; i++) {
            var parent = marks[i].parentNode;
            parent.replaceChild(document.createTextNode(marks[i].textContent), marks[i]);
            parent.normalize();
        }
    }

    function highlightText(node, query) {
        if (!query) return 0;
        var count = 0;
        var lowerQuery = query.toLowerCase();

        if (node.nodeType === 3) { // TEXT_NODE
            var text = node.textContent;
            var lowerText = text.toLowerCase();
            var idx = lowerText.indexOf(lowerQuery);
            if (idx >= 0) {
                var span = document.createElement('mark');
                span.className = 'search-highlight';
                var after = node.splitText(idx);
                after.splitText(query.length);
                span.appendChild(after.cloneNode(true));
                after.parentNode.replaceChild(span, after);
                count = 1;
            }
        } else if (node.nodeType === 1 && node.nodeName !== 'SCRIPT' &&
                   node.nodeName !== 'STYLE' && node.nodeName !== 'MARK' &&
                   node.nodeName !== 'INPUT') {
            var children = Array.prototype.slice.call(node.childNodes);
            for (var i = 0; i < children.length; i++) {
                count += highlightText(children[i], query);
            }
        }
        return count;
    }

    function doSearch() {
        clearHighlights();
        var query = searchBox.value.trim();
        if (query.length < 2) {
            searchCount.textContent = '';
            return;
        }

        // 모든 섹션 열기
        var details = contentEl.querySelectorAll('details');
        for (var i = 0; i < details.length; i++) {
            details[i].open = true;
        }

        var total = highlightText(contentEl, query);
        searchCount.textContent = total > 0
            ? total + '건 발견'
            : '검색 결과 없음';

        // 첫 번째 결과로 스크롤
        var first = contentEl.querySelector('mark.search-highlight');
        if (first) {
            first.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    searchBox.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(doSearch, 250);
    });

    // --- 전체 펼치기/접기 ---
    document.getElementById('btn-expand-all').addEventListener('click', function() {
        var details = contentEl.querySelectorAll('details');
        for (var i = 0; i < details.length; i++) details[i].open = true;
    });

    document.getElementById('btn-collapse-all').addEventListener('click', function() {
        var details = contentEl.querySelectorAll('details');
        for (var i = 0; i < details.length; i++) details[i].open = false;
    });

    // --- 맨 위로 버튼 ---
    var topBtn = document.getElementById('btn-top');
    window.addEventListener('scroll', function() {
        if (window.scrollY > 300) {
            topBtn.classList.add('visible');
        } else {
            topBtn.classList.remove('visible');
        }
    });
    topBtn.addEventListener('click', function() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
})();
