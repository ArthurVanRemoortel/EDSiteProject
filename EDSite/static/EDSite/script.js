function defaultProcessResults (data, params) {
    const results = $.map(data.results, function (obj) {
        obj.text = obj.name;
        return obj;
    });
    return {
        results: results,
        pagination: {
            more: data.next !== null
        }
    };
}

function defaultDataFunction (data, params) {
    var results = $.map(data.results,function (obj) {
        obj.text = obj.name;
        return obj;
    });
    return {
        results: results,
        pagination: {
            more: data.next !== null
        }
    };
}


function makeSelect2($inputRef, queryUrl, processResults, dataFunction, formatFunction, formatSelectionFunction, placeholder) {
    $inputRef.select2({
        ajax: {
            delay: 500,
            url: queryUrl,
            dataType: "json",
            type: "GET",
            data: function (params) {
                return {
                    name_like: params.term,
                    page: params.page || 1
                };
            },
            processResults: processResults,
            cache: false
        },
        minimumInputLength: 3,
        templateResult: formatFunction,
        templateSelection: formatSelectionFunction,
        placeholder: placeholder,
        allowClear: true
    });
}

function createExternalLinkTippy(itemId, templateId, placement='top'){
    const template = document.getElementById(templateId);
    tippy('#' + itemId, {
        interactive: true,
        allowHTML: true,
        content: template.innerHTML,
        delay: [400, 100],
        animation: 'shift-away',
        placement: placement,
        touch: ['hold', 100]
    });
}

