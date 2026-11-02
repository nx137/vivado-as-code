# fixture C：变量形式的 module_ref + IP，用于验证 check_handoff / bd_diff 的解析
set processing_system7_0 [ create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0 ]

set block_name adc_3pa1030_sync
set block_cell_name adc_3pa1030_sync_0
if { [catch {set adc_3pa1030_sync_0 [create_bd_cell -type module -reference $block_name $block_cell_name] } errmsg] } {
   catch {common::send_gid_msg -ssname BD::TCL -id 2095 -severity "ERROR" "Unable to add referenced block <$block_name>."}
}
