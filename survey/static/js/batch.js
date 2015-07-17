$(function(){


    $('#id_groups').on('change', function () {
    	reload_questions_lib();
    });
    $('#test').on('change', function () {
    	keyword_reload_questions_lib();
    });
    $('#id_modules').on('change', function () {
    	reload_questions_lib();
    });
    $('#id_question_types').on('change', function () {
    	reload_questions_lib();
    });
    $('.switch-open-close').on('switch-change', function (e, data) {
        var $this = $(this);
        var nonResponseSwitch = $this.parents("tr").find('.switch-activate-non-response');
        toggleStatus($this, ['open-for-location-form', 'close-for-location-form'], data);
        toggle_($this, nonResponseSwitch);
    });

    $('.switch-activate-non-response').on('switch-change', function (e, data) {
        toggleStatus($(this), ['activate-non_response-for-location-form', 'deactivate-non_response-for-location-form'], data)
    });

    var survey_id = $("#survey_id").val(),
        $add_batch_form = $('#add-batch-form');

    $add_batch_form.validate({
        rules: {
            'name': {required: true, remote: '/surveys/' + survey_id + '/batches/check_name/'},
            'description': 'required'
        },
////        messages: {
////            "name": {
////                remote: $.format("Batch with the same name already exists.")
////            }
//        }

    });

    $('#edit-batch-form').validate({
        rules: {
            'name': 'required',
            'description': 'required'
        }
    });



});

function reload_questions_lib()
{

	var group_selected = $('#id_groups').val();
    var module_selected = $('#id_modules').val();
    var answer_type_selected = $('#id_question_types').val();
    url = '/question_library/json_filter/';
    params = { question_types: answer_type_selected, groups : group_selected, modules: module_selected }
    $.getJSON(url, params, function (data) {
        $('.ms-selectable').hide()
        $.each(data, function () {
            $('#' + this.id + '-selectable').show();
        });
    });
}


function keyword_reload_questions_lib()
{
	alert($('#library_search_form input[text]').val());
	
}
function toggleStatus(element, forms_ids, data) {
    element.parent().find('.error').remove();
    var $el = $(data.el), form;
    if (data.value) {
        form = $el.parents('tr').find('form#' + forms_ids[0]);
    } else {
        form = $el.parents('tr').find('form#' + forms_ids[1]);
    }
    $.post(form.attr('action'), form.serializeArray(), function (data) {
        if (data != '') {
            element.bootstrapSwitch('toggleState');
            element.bootstrapSwitch('setActive', false);
            element.after('<span><label class="error">' + data + '</label></span>');
        }
    });

}

function toggle_($this, nonResponseSwitch) {
    nonResponseSwitch.bootstrapSwitch('setActive', true);
    nonResponseSwitch.next('span').hide();

    if (!$this.bootstrapSwitch('status')) {
        nonResponseSwitch.bootstrapSwitch('setState', false);
    }

}

