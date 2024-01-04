
$(document).ready(function() {
    // Get/set the cookie value for the ticket selector
    if (localStorage.getItem("whosw") === null) {
        localStorage.setItem("whosw", "mine");
    }

    if (direct_reports_count > 0) {
        // Show the selector and associated instructions.
        $('.dreport').show()
        // Set the ticket selector to the value in the cookie
        $('#whosselector').val(localStorage.getItem("whosw")).change();
    } else {
        // Handles someone that had reports, but doesnt now.
        localStorage.setItem("whosw", "mine");
    }

    // Setup - add a text input to each footer cell
    $('#utable tfoot th').each( function () {
        var title = $(this).text();
        if (title === 'Created On') {
            $(this).html('<input type="text" class="form-control form-control-sm" id="date-range1" placeholder="Enter date range"/>');
        } else if (title == 'id' || title == 'Task Count') {
            $(this).html( '' );
		} else if (title == 'Status') {
			$(this).html('<select class="form-select form-select-sm" id="projstatus"> \
			                    <option value="">All</option>\
			                    <option value="allopen" selected>(All Open)</option>\
			                    <option value="allclosed">(All Closed)</option>\
                                <option value="New">New</option>\
                                <option value="In Progress">In Progress</option>\
                                <option value="On Hold">On Hold</option>\
                                <option value="Pending Info">Pending Info</option>\
                                <option value="Cancelled">Cancelled</option>\
                                <option value="Completed">Completed</option>\
							</select>')
		} else if (title == 'Priority') {
			$(this).html('<select class="form-select form-select-sm" id="projpriority"> \
                            <option value="">All</option>\
                            <option value="Proposed">Proposed</option>\
                            <option value="Non Urgent">Non Urgent</option>\
                            <option value="Urgent">Urgent</option>\
                            <option value="Emergent">Emergent</option>\
							</select>')
        } else {
            $(this).html( '<input type="text" class="form-control form-control-sm" id="'+title+'" placeholder="Filter '+title+'" />' );
        }
    });

    // Powers the clear-all button in datatables.  Resets column and table search.
    $.fn.dataTable.ext.buttons.clear = {
        text: 'Clear/Refresh',
        action: function ( e, dt, node, config ) {
            table.columns().every( function () {
                let ele;
                if (this.footer().firstChild) {
                    ele = document.getElementById(this.footer().firstChild.id)
                    if (ele.nodeName === 'SELECT') {
                        ele.value = ele.firstElementChild.value
                    } else {
                        ele.value = ''
                    }
                }
            })
            $("input.form-control:text").val("");
            table.columns().search('');
            table.search('');
            table.order([1, 'desc']).draw();
        }
    };

    $.fn.dataTable.render.ellipsis = function (cutoff) {
        return function ( data, type, row ) {
            if (data.length > cutoff && type === 'display') {
                let shortened = data.substring(0,cutoff-1)
                return `<span
                  data-coreui-toggle="popover" data-coreui-trigger="hover" data-coreui-placement="top"
                     data-coreui-content="${data}">${shortened.replace(/\s([^\s]*)$/, '')}...</span>`
            } else {
                return data
            }
        }
    };

    //Creates main datatable
    var table = $("#utable").DataTable({
        pagingType: "full",
        serverSide: true,
        processing: true,
        stateSave: true,
        stateSaveParams: function (settings, data) {
            data.search.search = "";
            delete data.order;
            data.start = 0;
            delete data.columns;
        },
        lengthMenu: [[50, 10, 25, 100, -1], [50, 10, 25, 100, "All"]],
        dom: "<'row'<'col-sm-5 pagination-sm'p><'col-sm-4'B><'col-sm-3'f>>" +
            "<'row'<'col-sm-12'tr>>" +
            "<'row'<'col-sm-5'i><'col-sm-5'><'col-sm-1'l>>",
        order: [[1, 'desc']],
        ajax: {
            "url": url,
            "type": 'GET',
            "data": function(d){
                    d.whos = localStorage.getItem("whosw");
                    d.tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
                },
        },
        buttons: [
            { extend: 'clear', className: 'btn btn-light btn-sm' },
        ],
        columnDefs: [
            {
                targets: 2,
                render: $.fn.dataTable.render.ellipsis(35)
            },
            {
                targets: 5,
                render: $.fn.dataTable.render.ellipsis(20)
            },
        ],
        columns: [
            {
                className: 'details-control',
                orderable: false,
                data: null,
                defaultContent: '',
            },
            {data: 'project_num',
                render: function (data, type, row) {
                    return '<a href="' + row.id + '">' + data + '</a>';
                }
            },
            {data: 'short_desc'},
            {data: "status"},
            {data: "priority"},
            {data: "assigned_to", orderable: false},
            {data: 'created_by_name'},
            {data: 'created_at',
                render: function (data, type, row) {
                    return moment.utc(data).local().format('MM/DD/YY, h:mma');
                }
            },
            // {data: 'tasks',
            //     render: function (data, type, row) {
            //         return data.length;
            //     }, orderable: false
            // },
        ],

    });

    //Moves column search to top row under column headers
    $('#utable tfoot tr').appendTo('#utable thead');

    // Apply and send the single column search.
    // Takes column search variables and submits to datatables
    table.columns().every( function () {
        var that = this;

        $( 'select', this.footer() ).change(function(event) {
            if ( that.search() !== this.value) {
                that.search( this.value ).draw();
            }
        });

        $( 'input', this.footer() ).keyup(function(event) {
            if (event.keyCode === 13) {
                if ( that.search() !== this.value) {
                    var val = this.value
                    that.search(val).draw();
                }
            }
        });
    });

    // Modifies general search so that it only fires on enter
    $('.dataTables_filter input').unbind().bind('keyup', function(e) {
        if(e.keyCode == 13) {
            table.search($(this).val()).draw();
        }
    });

    //Generates date range picker on created on column.
    $('#date-range1').daterangepicker({
        separator : '<>',
        format: 'MM/DD/YYYY',
        autoClose: false,
    }).on('datepicker-apply',function(event,obj) {
        let all_header_column_names = table.columns().header().map(d => d.textContent).toArray()
        let index_of_date_column = all_header_column_names.indexOf('Created On')
        table.columns( index_of_date_column ).search(obj.value).draw(); //Pulls value from "sent" column
    }).keypress(function(e) {
        //Stop user from being able to type in the date search bar.
        e.preventDefault();
    });

    // Controller for child sub-table rollout
    // https://datatables.net/examples/api/row_details.html
    $('#utable tbody').on('click', 'td.details-control', function () {
        var tr = $(this).closest('tr');
        tr.toggleClass('details'); // Clicking the plus sign toggles the select. This unselects it.
        var row = table.row( tr );

        if ( row.child.isShown() ) {
            $('div.slider', row.child()).slideUp( function () {
                // This row is already open - close it
                row.child.hide();
                tr.removeClass('shown');
            });
        }
        else {
            // Open this row
            row.child( format(row.data()), 'no-padding' ).show();
            tr.addClass('shown');
            $('div.slider', row.child()).slideDown();
        }
    });

    // Populates child subtable when plus-minus button is hit
    function format ( d ) {
        // `d` is the original data object for the row
        // Start building table html string
        let tdata = get_tasks(d.id) // Call to the API to get the last 10 data
        child_table = `<div class="slider"><h5 style="margin-top: 5px; margin-left: 14px">Tasks for ${d.project_num}</h5>`
        child_table += '<table class="subtable" id="table_' + d.id + '" cellpadding="5" cellspacing="0" border="0" style="width: 90%; margin: 15px; white-space: normal!important;"><thead>'
        child_table += '<tr style="background-color:silver;"><th>Task#</th><th>Description</th><th>Created By</th><th>Status</th><th>Assigned To</th></tr></thead>'
        child_table += '<tbody><tr style="background-color:whitesmoke;"><td colspan="5">Loading...</td></tr></tbody>'
        child_table += '</table></div>'
        return child_table;
    }

    // When ticket selector changes, update cookie and reset search values to null.
    $('#whosselector').change(function(){
        localStorage.setItem("whosw", this.value);
        $("input.form-control:text").val("");
        $('input[name="datefilter"]').val("");
        $('#projstatus').val('All').change();
        $('#projpriority').val('All').change();
        table.search( '' ).columns().search( '' ).draw();
        //table.ajax.reload();
    });
});

