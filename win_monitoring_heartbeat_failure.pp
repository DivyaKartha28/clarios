# Gather cpu queue length information for the given VM 
plan ntt_monitoring::win_monitoring_heartbeat_failure (
  TargetSpec $targets,   
  String $dns_domain,
  String $serviceslist,
  String $serviceretry,
  String $forcerestart   
) {
  # load in StackStorm variables from the datastore (if specified)
  run_plan('ntt_monitoring::st2kv_env', $targets)

  $result = run_task('ntt_monitoring::win_monitoring_heartbeat_failure', $targets,
                      dns_domain => $dns_domain,
					  serviceslist => $serviceslist,
            serviceretry => $serviceretry,
            forcerestart => $forcerestart)				  
  $script_output = $result.first().value['_output'] 
  $server_service_status_split = split($script_output, 'Final Service state :')[1] 
  $server_service_status = split($server_service_status_split, "on")[0]
  $server_service_status_lstrip = $server_service_status.lstrip()
  $server_service_status_rstrip = $server_service_status_lstrip.rstrip() 
  
  $server_uptime_split = split($script_output, 'UpTime :')[1]
  $server_uptime = split($server_uptime_split, " days")[0]
  $server_uptime_lstrip = $server_uptime.lstrip()
  $server_uptime_lstrip_rstrip = $server_uptime_lstrip.rstrip()
  
  $event1074_split = split($script_output, 'Event ID 1074 :')[1]
  $event1074 = split($event1074_split, "on")[0]
  $event1074_lstrip = $event1074.lstrip()
  $event1074_rstrip = $event1074_lstrip.rstrip()
  
  $result_hash = {"output" => $script_output, "server_service_status" => $server_service_status_rstrip,"server_uptime_days" => $server_uptime_lstrip_rstrip,"event1074" => $event1074_rstrip}
  return $result_hash
}


