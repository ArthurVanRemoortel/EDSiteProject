
function makeSelect2($inputRef, queryUrl, formatFunction, formatSelectionFunction, placeholder) {
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
            processResults: function (data, params) {
                return {
                    results: $.map(data.results, function(item) {
                        return {
                            id: item.id,
                            text: item.name,
                            name: item.name,
                        }}),
                    pagination: {
                        more: data.next !== null
                    }
                };
            },
            cache: false
        },
        minimumInputLength: 3,
        templateResult: formatFunction,
        templateSelection: formatSelectionFunction,
        placeholder: placeholder,
    });
}




