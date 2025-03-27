Param(
  [String]$dns_domain,  
  [String]$ServicesList,
  [String]$serviceretry,
  [String]$forcerestart
)

$hostname = hostname
$Services = $ServicesList.split(",")
  if ($dns_domain)
  {
    $machine = $hostname + '.' + $dns_domain
  }
  else
  {
    $machine = $hostname
  }

  $CheckHost = $env:COMPUTERNAME
  try {
    $HostIP = [System.Net.Dns]::GetHostAddresses($machine) | ? { $_.scopeid -eq $null } | % { $_.ipaddresstostring }
} catch {
    Write-Output "Error: Unable to resolve hostname $machine. Please check the hostname and DNS configuration."
    exit 1
}

  $error.clear()  
  $global:Service_Inc_escalate = "running on server"

		
Function Heartbeat
{
#$machines=get-content((Read-Host 'Enter the computers list file Path here') -replace '"')
#foreach($machine in $machines)

	$Pingcheck= Test-Connection -ComputerName $machine -count 1 -Quiet
	$pathtest= Test-Path \\$machine\c$

	if($Pingcheck -eq "true" -and $pathtest -eq "true")	{
		$uptime=Get-WmiObject win32_operatingsystem -ComputerName $machine| select csname, @{LABEL='LastBootUpTime';EXPRESSION={$_.ConverttoDateTime($_.lastbootuptime)}}
		write-output "Server name being checked : $machine"
		write-output "Pingable : true"
		write-output "Pinged IP : $HostIP"
		write-output "$machine is pingable from $CheckHost"
		    $OS = Get-WmiObject win32_operatingsystem -ComputerName $machine -ErrorAction SilentlyContinue
			$BootTime = $OS.ConvertToDateTime($OS.LastBootUpTime) 
            $Uptime = $OS.ConvertToDateTime($OS.LocalDateTime) - $boottime 
            $Display = "Uptime: " + $Uptime.Days + " days, " + $Uptime.Hours + " hours, " + $Uptime.Minutes + " minutes" 
            $UptimeMinutes = (24*60)*$Uptime.Days + (60)*$Uptime.Hours + $Uptime.Minutes
            $MinutesToCheck = 120
			$osname=$OS.Caption
			"SNAPSHOTSTART`n"
            "System Information"
            "------------------------------"
            "OS Version : $osname"
            "UpTime : " + $Uptime.Days + " days, " + $Uptime.Hours + " hours, " + $Uptime.Minutes + " minutes " + "(Total Minutes: " + $UptimeMinutes + ")"
            "Last Boot Time : $BootTime"
		trap [System.Management.Automation.RuntimeException]
        {
            if (($_.Exception.GetType().FullName -eq "System.UnauthorizedAccessException") -or($_.Exception.GetType().FullName -eq "System.Management.Automation.RuntimeException"))
            { 
             throw $_
            } 
         write-output ""
         ##write-output "Event not found"
         write-output ""
         continue;
		}
		write-output "Server Name: $machine"
         #write-output "##### Event 1074"
         #$event=1074
		 Write-Output "---------------EVENT LOGS DETAILS START------------------"
		#$(Get-EventLog -ComputerName $machine -LogName System -newest 1 -message *restart* ; Get-EventLog -ComputerName $machine -LogName System -newest 1 -message *shutdown*)| select-object TimeWritten,EntryType,Source,EventID,Username,Message | fl
		$Event_log_Restart =(Get-EventLog -ComputerName $machine -LogName System -newest 1 -message *restart*)| select-object TimeWritten,EntryType,Source,EventID,Username,Message | fl | out-string
		$Event_log_shutdown =(Get-EventLog -ComputerName $machine -LogName System -newest 1 -message *shutdown*)| select-object TimeWritten,EntryType,Source,EventID,Username,Message | fl | out-string
		Write-Output $Event_log_Restart
		Write-Output $Event_log_shutdown		
		$SearchTerm ="1074"
		if (($Event_log_Restart -match $SearchTerm) -or ($Event_log_shutdown -match $SearchTerm)) { 
		Write-Output "Event ID 1074 : found on server" 
		} else { 
		Write-Output "Event ID 1074 : Not_found on server" 
		}
		Write-Output "---------EVENT LOGS DETAILS END--------"
	    write-output "Working on service check "
		#[Array] $Services = 'opsramp-agent','opsramp-shield';
		#[Array] $Services = 'SNMP Trap','Remote Desktop Services';
		foreach($ServiceName in $Services)
		{
		   $service_retry_counter = 0
		   $service_retry_limit = [int]$serviceretry
		   $force_restart_flag = [int]$forcerestart
		   function ServiceRestart($srvName)
		   {
			   write-output "Automation trying to Restart the Service"
			   write-output "Retry Attempt : $service_retry_counter" 
			   $SvcName2 = get-wmiobject Win32_Service -computername $machine -ErrorAction SilentlyContinue| where-object {($_.Name -eq $srvName) -or ($_.DisplayName -eq $srvName)}
			   $SvcName2.StopService()
			   Start-Sleep -seconds 30
			   $SvcName2.StartService() 		       
               Start-Sleep -seconds 300
               $SvcName3 = get-wmiobject Win32_Service -computername $machine -ErrorAction SilentlyContinue| where-object {($_.Name -eq $srvName) -or ($_.DisplayName -eq $srvName)}
               $Svcstartmode3=$SvcName3.StartMode			   
               if ($SvcName3.state -eq "Running" -and $Svcstartmode3 -ne "Disabled") {
               write-output "Service state : running on server" 
			   write-output $SvcName3
               }else{
				if ($service_retry_counter -lt $service_retry_limit){
		        write-output "Service state : fail_to_start on server"
				 write-output $SvcName3	
				$service_retry_counter++ 
				ServiceRestart $srvName
				}else{
				 write-output "Service state : fail_to_start on server"
				 $global:Service_Inc_escalate = "fail_to_start on server"
				 write-output $SvcName3	
				}	   
		       }			   
		   }
		   write-output "-----------------------------------------"
           write-output "Service name:$ServiceName"
           $loopCounter++
           try{
		   $service = Get-Service -Name $ServiceName -ErrorAction Stop
           $status=Get-Service -ServiceName $ServiceName  -ComputerName $machine | select name, status, machinename | sort machinename | format-table -AutoSize
		   if ( $force_restart_flag -eq 1 ){
			ServiceRestart $ServiceName
		   }
		   else{
		   switch ($service.Status){
           'Stopped'{write-output "$ServiceName is stopped" ;  ServiceRestart $ServiceName  ;  }
           'Running'{write-output "Service state : running on server" ; $status ;}
		   'Disabled'{write-output "Service state : disabled on server" ; ServiceRestart $ServiceName ; }
           Default{write-output "Service state : Service_is_not_available on server";$global:Service_Inc_escalate = "Service_is_not_available on server"}
		   }
           }
		   }catch{
		   if ( $error[0].Exception -match "Cannot find any service with service name"){
			write-output "Service state : Service_is_not_available on server"
			$global:Service_Inc_escalate = "Service_is_not_available on server"
           }else{
		    write-output "Service state : fail_to_start on server "
			$global:Service_Inc_escalate = "fail_to_start on server "
           }   
           }		   	
           write-output "-----------------------------------------"		   
		}
	}else {	
		write-output "$machine is not reachable from $CheckHost ($HostIP)" -ForegroundColor Red
		write-output "Server name being checked : $machine"
		write-output "Pingable : false"
		write-output "Pinged IP : $HostIP"
		write-output "$machine is not pingable from $CheckHost"
		write-output ""  
	}
	
}
Heartbeat
write-output "-----------------------------------------"	
write-output "Final Service state : $global:Service_Inc_escalate"	
write-output "-----------------------------------------"
write-output "Event logs of Opsramp Agent service"
Get-EventLog -LogName "System" -Source "Service Control Manager" -EntryType "Information" -Newest 1 -Message "*g*" | select-object TimeWritten,EntryType,Source,EventID,Username,Message | fl


