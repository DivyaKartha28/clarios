
#!/usr/bin/env python
# Copyright 2021 Encore Technologies
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# https://www.w3schools.com/python/trypython.asp?filename=demo_ref_string_split3
from st2reactor.sensor.base import PollingSensor
from st2client.models.keyvalue import KeyValuePair  # pylint: disable=no-name-in-module
import requests
import ast
import socket
import os
from st2client.client import Client
import sys
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../actions/lib')
import base_action
import re
from datetime import datetime, timedelta

__all__ = [
    'ServiceNowIncidentSensorOpsRamp'
]


class ServiceNowIncidentSensorOpsRamp(PollingSensor):
    def __init__(self, sensor_service, config=None, poll_interval=None):
        super(ServiceNowIncidentSensorOpsRamp, self).__init__(sensor_service=sensor_service,
                                                       config=config,
                                                       poll_interval=poll_interval)
        self._logger = self._sensor_service.get_logger(__name__)
        self.base_action = base_action.BaseAction(config)

    def setup(self):
        self.sn_username = self.config['servicenow']['username']
        self.sn_password = self.config['servicenow']['password']
        self.sn_url = self.config['servicenow']['url']
        self.som_company_sys_id = self.config['servicenow']['company_sys_id']
        self.servicenow_headers = {'Content-type': 'application/json',
                                   'Accept': 'application/json'}
        self.st2_fqdn = socket.getfqdn()
        st2_url = "https://{}/".format(self.st2_fqdn)
        self.st2_client = Client(base_url=st2_url)

    def poll(self):
        # Query for all active and open incidents
        self._logger.info('STARTED_OPSRAMP_INCIDENT_SENSOR_AT: {}'.format(datetime.now()))

        sn_inc_endpoint = '/api/now/table/incident?sysparm_query=active=true^incident_state=2'
        sn_inc_endpoint = sn_inc_endpoint + '^company.sys_id='+self.som_company_sys_id
        sn_inc_endpoint = sn_inc_endpoint + '^priority=3^ORpriority=4'
        sn_inc_endpoint = sn_inc_endpoint + '^sys_created_on>=javascript:gs.beginningOfYesterday()'

        # Windows/Linux CPU Utilization
        sn_inc_endpoint = sn_inc_endpoint + '^short_descriptionLIKEsystem.cpu.usage.utilization'

        # Windows/Unix Memory Utilization
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEsystem.memory.physical.utilization'
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEsystem.memory.virtual.utilization'
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEsystem.memory.cache.utilization'
        # sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEsystem_linux_swapMemory_Utilization'
        # sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEMemory%20Usage%20On'

        # Windows/ Linux System uptime and host down
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEsystem.os.uptime'
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEPacket%20Loss'
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEIs%20not%20responding%20to%20Ping'


        # Windows Disk usage
        sn_inc_endpoint = sn_inc_endpoint + '^ORdescriptionLIKEDisk%20C%20is'

        # Linux Disk usage
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEDisk%20%2Fvar'

        # Windows Service alert
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEservice%20stopped'

        #OpsRamp Agent Offline
        sn_inc_endpoint = sn_inc_endpoint + '^ORshort_descriptionLIKEOpsRamp%20agent%20is%20offline'

        # define the which fiels needs to return from SOM API
        sn_inc_endpoint = sn_inc_endpoint + '&sysparm_fields=number,assignment_group,company,cmdb_ci,description,short_description,sys_id,priority,incident_state,opened_at'

        sn_inc_url = "https://{0}{1}".format(self.sn_url,sn_inc_endpoint)
        self._logger.info('INC url: ' + str(sn_inc_url))
        proxy1 = { 'https': 'http://proxy.clarios.com:443' }
        sn_result = requests.request('GET',sn_inc_url,auth=(self.sn_username, self.sn_password),headers=self.servicenow_headers,proxies=proxy1)

        sn_result.raise_for_status()
        sn_incidents = sn_result.json()['result']
        self.check_incidents(sn_incidents)
        self._logger.info('COMPLETED_OPSRAMP_INCIDENT_SENSOR_AT: {}'.format(datetime.now()))

    def check_incidents(self, sn_incidents):
        ''' Create a trigger to run cleanup on any open incidents that are not being processed
        '''
        inc_st2_key = 'servicenow.incidents_processing'
        processing_incs = self.st2_client.keys.get_by_name(inc_st2_key)

        processing_incs = [] if processing_incs is None else ast.literal_eval(processing_incs.value)

        for inc in sn_incidents:
            # skip any incidents that are currently being processed
            if inc['number'] in processing_incs:
                #self._logger.info('Already processing INC: ' + inc['number'])
                continue
            else:
                insert_output = self.check_description(inc)
                if insert_output == "true":
                    self._logger.info('Processing INC: ' + inc['number'])
                    processing_incs.append(inc['number'])
                    incs_str = str(processing_incs)
                    kvp = KeyValuePair(name=inc_st2_key, value=incs_str)
                    self.st2_client.keys.update(kvp)
                else:
                    continue


    def get_support_group(self, inc):
        assign_group = ''
        if inc['cmdb_ci'] and inc['cmdb_ci']['link']:
            ci_data = self.base_action.sn_api_call(method='GET',
                                                   url=inc['cmdb_ci']['link'])
            if ci_data['support_group'] and ci_data['support_group']['link']:
               response = self.base_action.sn_api_call(method='GET',
                                                   url=ci_data['support_group']['link'])
               assign_group = response['name']
               self._logger.info('Assignment Group fetched for INC: ' + assign_group)
               self._logger.info('Assignment Group fetched for INC: ' + inc['number'])
            else:
               if 'redhat' in ci_data['category'].lower() or 'linux' in ci_data['category'].lower() or 'unix' in ci_data['category'].lower():
                   assign_group = 'unix'
               elif 'wintel' in ci_data['category'].lower() or 'windows' in ci_data['category'].lower():
                   assign_group = 'wintel'
               else:
                   assign_group = ''
                   self._logger.info('Assignment Group not found for INC: ' + inc['number'])
        else:
            self._logger.info('Assignment Group not found for INC: ' + inc['number'])
            assign_group = ''

        return assign_group


    def get_company_and_ag_and_ciname(self, inc):
        configuration_item_env = ''
        if inc['assignment_group'] and inc['assignment_group']['link']:
            response = self.base_action.sn_api_call(method='GET',
                                                    url=inc['assignment_group']['link'])
            assign_group = response['name']
            if 'Clarios-Service Management' in assign_group or 'Clarios-Service Desk Ind_Blr' in assign_group:
                assign_group = self.get_support_group(inc)
        else:
            self._logger.info('Assignment Group not found for INC: ' + inc['number'])
            assign_group = ''

        if inc['company'] and inc['company']['link']:
            response = self.base_action.sn_api_call(method='GET',
                                                   url=inc['company']['link'])
            company = response['name']
        else:
            self._logger.info('Company not found for INC: ' + inc['number'])
            company = 'Clarios'

        if inc['cmdb_ci'] and inc['cmdb_ci']['link']:
            response = self.base_action.sn_api_call(method='GET',
                                                   url=inc['cmdb_ci']['link'])
            configuration_item_name = response['name']
            configuration_item_env = response['u_environment'].lower()
        else:
            self._logger.info('Company not found for INC: ' + inc['number'])
            configuration_item_name = ''

        return assign_group, company,configuration_item_name,configuration_item_env



    def betweenString(self,value, a, b):
        # Find and validate before-part.
        pos_a = value.find(a)
        if pos_a == -1: return ""
        # Find and validate after part.
        pos_b = value.rfind(b)
        if pos_b == -1: return ""
        # Return middle part.
        adjusted_pos_a = pos_a + len(a)
        if adjusted_pos_a >= pos_b: return ""
        return value[adjusted_pos_a:pos_b]

    def afterString(self,value, a):
        # Find and validate first part.
        pos_a = value.rfind(a)
        if pos_a == -1: return ""
        # Returns chars after the found string.
        adjusted_pos_a = pos_a + len(a)
        if adjusted_pos_a >= len(value): return ""
        return value[adjusted_pos_a:]

    def beforeString(self,value, a):
        # Find first part and return slice before it.
        pos_a = value.find(a)
        if pos_a == -1: return ""
        return value[0:pos_a]

    def check_description(self, inc):
        insertto_datastore = 'false'
        desc_org = inc['description']
        desc = inc['description'].lower()
        short_desc = inc['short_description']
        short_desc_lower = inc['short_description'].lower()
        ci_address , ci_address_temp = "", ""

        assign_group, company, configuration_item_name,configuration_item_env = self.get_company_and_ag_and_ciname(inc)

        rec_short_desc = ""
        rec_detailed_desc = ""

        # Find_After = self.afterString(short_desc, "OpsRamp - ")
        # Find_After = Find_After.strip()
        # Find_Before = self.beforeString(Find_After, ' ')
        # ci_address = Find_Before.strip()

        # Windows System UpTime , Windows Hostdown Ping failure
        if ('system.os.uptime' in short_desc_lower or 'packet loss' in short_desc_lower or 'is not responding to ping' in short_desc_lower ) and ('wintel' in assign_group.lower() or 'intel' in assign_group.lower() or 'unix' in assign_group.lower() or 'clarios-uscan fieldservice l3' in assign_group.lower() or 'clarios-hypervisor support' in assign_group.lower() or 'nttds-central hypervisor support' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower() or 'nttds-is storage infrastructure' in assign_group.lower() or 'nttds-storage l1' in assign_group.lower() ):
            insertto_datastore = "true"
            if ('unix' in assign_group.lower() or 'clarios-hypervisor support' in assign_group.lower() or 'nttds-central hypervisor support' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower() or 'nttds-is storage infrastructure' in assign_group.lower() or 'nttds-storage l1' in assign_group.lower()):
                os_type='linux'
            else:
                #os_type='linux'
                os_type='windows'

            if 'nttds-publiccloudops' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'linux' in assign_group.lower() or 'unix' in assign_group.lower():
                    os_type = 'linux'
                else:
                    os_type = 'windows'

            if 'system.os.uptime' in short_desc_lower:
                rec_short_desc = 'system.os.uptime'
                rec_detailed_desc = 'system.os.uptime'

                if configuration_item_name:
                    ci_address = str(configuration_item_name).lower()
                else:
                    Find_After = self.afterString(short_desc, "OpsRamp-")
                    Find_After = Find_After.strip()
                    Find_Before = self.beforeString(Find_After, ' ')
                    ci_address = Find_Before.strip()

            elif 'packet loss' in short_desc_lower:
                rec_short_desc = 'Packet Loss'
                rec_detailed_desc = 'Packet Loss'
                
                if configuration_item_name:
                    ci_address = str(configuration_item_name).lower()
                else:
                    Find_After = self.afterString(short_desc, "OpsRamp ")
                    Find_After = Find_After.strip()
                    Find_Before = self.beforeString(Find_After, ' ')
                    ci_address = Find_Before.strip()

                

            elif 'is not responding to ping' in short_desc_lower:
                rec_short_desc = 'Is not responding to Ping'
                rec_detailed_desc = 'Is not responding to Ping'
                
                if configuration_item_name:
                    ci_address = str(configuration_item_name).lower()
                else:
                    Find_After = self.afterString(short_desc, "OpsRamp -")
                    Find_After = Find_After.strip()
                    Find_Before = self.beforeString(Find_After, ' ')
                    ci_address = Find_Before.strip()

            ci_address = ci_address.strip()
            ci_address = ci_address.lower()


            payload = {
                'assignment_group': assign_group,
                'check_uptime': 'true',
                'ci_address': ci_address,
                'customer_name': company,
                'detailed_desc': inc['description'],
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'os_type': os_type,
                'short_desc': inc['short_description'],
                'rec_short_desc': rec_short_desc,
                'rec_detailed_desc': rec_detailed_desc,
                'configuration_item_name': configuration_item_name
            }
            self._sensor_service.dispatch(trigger='ntt_itsm.unreachable_ping', payload=payload)
            # self._logger.info('system payload' + str(payload))

        # Windows High CPU
        elif ('system.cpu.usage.utilization' in short_desc_lower) and ('wintel' in assign_group.lower() or 'intel' in assign_group.lower() or 'clarios-uscan fieldservice l3' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower()):

            insertto_datastore = "true"
            trigger_action = 'true'
            if 'nttds-publiccloudops' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'wintel' in assign_group:
                    trigger_action = 'true'
                else:
                    trigger_action = 'false'

            rec_short_desc = "system.cpu.usage.utilization"
            rec_detailed_desc = "system.cpu.usage.utilization"

            if 'th is' in short_desc_lower:
                threshold_begin = short_desc_lower.split('th is ')[-1]
                threshold = str(int(threshold_begin.split('%')[0]))
            else:
                threshold = '85'
                
            
            if configuration_item_name:
                ci_address = str(configuration_item_name).lower()
            else:
                Find_After = self.afterString(short_desc, "OpsRamp ")
                Find_After = Find_After.strip()
                Find_Before = self.beforeString(Find_After, ' ')
                ci_address = Find_Before.strip()

            ci_address = ci_address.strip()
            ci_address = ci_address.lower()


            payload = {
                'assignment_group': assign_group,
                'ci_address': ci_address,
                'cpu_name': '_total',
                'cpu_type': 'ProcessorTotalProcessorTime',
                'customer_name': company,
                'detailed_desc': inc['description'],
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'incident_state': inc['incident_state'],
                'os_type': 'windows',
                'short_desc': inc['short_description'],
                'threshold_percent': threshold,
                'rec_short_desc': rec_short_desc,
                'rec_detailed_desc': rec_detailed_desc,
                'configuration_item_name': configuration_item_name
            }

            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.high_cpu', payload=payload)
            else:
                insertto_datastore = "false"

        # Linux High CPU
        elif ('system.cpu.usage.utilization' in short_desc_lower) and ('linux' in assign_group.lower() or 'unix' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower()):

            insertto_datastore = "true"
            trigger_action = 'true'
            if 'nttds-publiccloudops' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'linux' in assign_group.lower() or 'unix' in assign_group.lower():
                    trigger_action = 'true'
                else:
                    trigger_action = 'false'

            rec_short_desc = "system.cpu.usage.utilization"
            rec_detailed_desc = "system.cpu.usage.utilization"

            if 'th is' in short_desc_lower:
                threshold_begin = short_desc_lower.split('th is ')[-1]
                threshold = str(int(threshold_begin.split('%')[0]))
            else:
                threshold = '85'
            
            
            if configuration_item_name:
                ci_address = str(configuration_item_name).lower()
            else:
                Find_After = self.afterString(short_desc, "OpsRamp ")
                Find_After = Find_After.strip()
                Find_Before = self.beforeString(Find_After, ' ')
                ci_address = Find_Before.strip()
            
            ci_address = ci_address.strip()
            ci_address = ci_address.lower()

            payload = {
                'assignment_group': assign_group,
                'ci_address': ci_address,
                'cpu_name': '_total',
                'cpu_type': 'ProcessorTotalProcessorTime',
                'customer_name': company,
                'detailed_desc': inc['description'],
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'incident_state': inc['incident_state'],
                'os_type': 'linux',
                'short_desc': inc['short_description'],
                'threshold_percent': threshold,
                'rec_short_desc': rec_short_desc,
                'rec_detailed_desc': rec_detailed_desc,
                'configuration_item_name': configuration_item_name
            }
            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.high_cpu_unix', payload=payload)
            else:
                insertto_datastore = "false"


        # Windows High Memory
        elif ('system.memory.physical.utilization' in short_desc_lower or 'system.memory.virtual.utilization' in short_desc_lower or 'system.memory.cache.utilization' in short_desc_lower) and ('wintel' in assign_group.lower() or 'intel' in assign_group.lower() or 'clarios-uscan fieldservice l3' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower()):
            insertto_datastore = "true"
            trigger_action = 'true'

            if 'nttds-publiccloudops' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'wintel' in assign_group:
                    trigger_action = 'true'
                else:
                    trigger_action = 'false'

            rec_short_desc = ''
            rec_detailed_desc = ''
            
            if configuration_item_name:
                ci_address = str(configuration_item_name).lower()
            else:
                Find_After = self.afterString(short_desc, "OpsRamp ")
                Find_After = Find_After.strip()
                Find_Before = self.beforeString(Find_After, ' ')
                ci_address = Find_Before.strip()
                
            ci_address = ci_address.lower()


            if 'system.memory.physical.utilization' in desc:
                rec_short_desc = 'system.memory.physical.utilization'
                rec_detailed_desc = 'system.memory.physical.utilization'
            elif 'system.memory.virtual.utilization' in desc:
                rec_short_desc = 'system.memory.virtual.utilization'
                rec_detailed_desc = 'system.memory.virtual.utilization'
            elif 'system.memory.cache.utilization' in desc:
                rec_short_desc = 'system.memory.cache.utilization'
                rec_detailed_desc = 'system.memory.cache.utilization'

            if ', th is' in short_desc_lower:
                threshold_begin = short_desc_lower.split(', th is ')[-1]
                threshold = str(int(threshold_begin.split('%')[0]))
            else:
                threshold = '90'

            if 'memory.physical' in desc:
                memory_type = 'Physical'
            elif 'memory.virtual' in desc:
                memory_type = 'Virtual'
            elif 'memory.cache' in desc:
                memory_type = 'Cache'
            else:
                memory_type = 'Physical'

            payload = {
                'assignment_group': assign_group,
                'ci_address': ci_address,
                'customer_name': company,
                'detailed_desc': inc['description'],
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'os_type': 'windows',
                'short_desc': inc['short_description'],
                'threshold_percent': threshold,
                'incident_state': inc['incident_state'],
                'rec_short_desc': rec_short_desc,
                'rec_detailed_desc': rec_detailed_desc,
                'configuration_item_name': configuration_item_name,
                'memory_type':memory_type
            }
            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.win_memory_high', payload=payload)
            else:
                insertto_datastore = "false"


        # Linux High Memory
        elif ('system.memory.physical.utilization' in short_desc_lower or 'system.memory.virtual.utilization' in short_desc_lower or 'system.memory.cache.utilization' in short_desc_lower) and ('linux' in assign_group.lower() or 'unix' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower()):
            insertto_datastore = "true"
            trigger_action = 'true'
            if 'nttds-publiccloudops' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'linux' in assign_group.lower() or 'unix' in assign_group.lower():
                    trigger_action = 'true'
                else:
                    trigger_action = 'false'

            rec_short_desc = ''
            rec_detailed_desc = ''
            
            if configuration_item_name:
                ci_address = str(configuration_item_name).lower()
            else:
                Find_After = self.afterString(short_desc, "OpsRamp ")
                Find_After = Find_After.strip()
                Find_Before = self.beforeString(Find_After, ' ')
                ci_address = Find_Before.strip()

            ci_address = ci_address.strip()
            ci_address = ci_address.lower()


            if 'system.memory.physical.utilization' in desc:
                rec_short_desc = 'system.memory.physical.utilization'
                rec_detailed_desc = 'system.memory.physical.utilization'
            elif 'system.memory.virtual.utilization' in desc:
                rec_short_desc = 'system.memory.virtual.utilization'
                rec_detailed_desc = 'system.memory.virtual.utilization'
            elif 'system.memory.cache.utilization' in desc:
                rec_short_desc = 'system.memory.cache.utilization'
                rec_detailed_desc = 'system.memory.cache.utilization'


            if ', th is' in short_desc_lower:
                threshold_begin = short_desc_lower.split(', th is ')[-1]
                threshold = str(int(threshold_begin.split('%')[0]))
            else:
                threshold = '85'



            payload = {
                'assignment_group': assign_group,
                'ci_address': ci_address,
                'customer_name': company,
                'detailed_desc': inc['description'],
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'os_type': 'linux',
                'short_desc': inc['short_description'],
                'threshold_percent': threshold,
                'incident_state': inc['incident_state'],
                'rec_short_desc': rec_short_desc,
                'rec_detailed_desc': ci_address,
                'configuration_item': configuration_item_name
            }
            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.memory_high_unix', payload=payload)
            else:
                insertto_datastore = "false"

        # Windows Low disk
        elif ('disk c is' in desc) and ('wintel' in assign_group.lower() or 'intel' in assign_group.lower() or 'nttds-publiccloudops' in assign_group.lower() or 'clarios-uscan fieldservice l3' in assign_group.lower()):

            insertto_datastore = "true"
            trigger_action = 'true'
            if 'nttds-publiccloudops' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'wintel' in assign_group.lower():
                    trigger_action = 'true'
                else:
                    trigger_action = 'false'

            disk_name = "C"

            rec_short_desc = 'Disk C'
            rec_detailed_desc = 'Disk C'

            if 'threshold is' in desc:
                threshold_begin = desc.split('threshold is ')[-1]
                threshold = str(int(threshold_begin.split('.')[0]))
            else:
                threshold = '90'

            threshold = float(threshold)
            threshold = 100 - int(threshold)
            threshold = str(threshold)
            
            if configuration_item_name:
                ci_address = str(configuration_item_name).lower()
            else:
                Find_After = self.afterString(short_desc, "OpsRamp ")
                Find_After = Find_After.strip()
                Find_Before = self.beforeString(Find_After, ' ')
                ci_address = Find_Before.strip()

            ci_address = ci_address.strip()
            ci_address = ci_address.lower()


            payload = {
                'assignment_group': assign_group,
                'ci_address': ci_address,
                'customer_name': company,
                'detailed_desc': inc['description'],
                'disk_name': disk_name,
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'os_type': 'windows',
                'short_desc': inc['short_description'],
                'threshold_percent': threshold,
                'threshold_type': 'percent',
                'threshold_mb': '0',
                'configuration_item_name': configuration_item_name,
                'rec_short_desc': rec_short_desc,
                'rec_detailed_desc': rec_detailed_desc
            }


            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.high_disk', payload=payload)
            else:
                insertto_datastore = "false"


        # elif (('service stopped' in short_desc_lower ) and ('intel' in assign_group.lower() or 'wintel' in assign_group.lower())) :
            #assign_group, company = self.get_company_and_ag(inc)
            # insertto_datastore = "true"

            # service_name = ""
            # service_string = short_desc.split('-')[-1]
            # Find_Before_service = self.beforeString(service_string, 'service stopped')
            # service_name = Find_Before_service.strip()


            # payload = {
            #     'assignment_group': assign_group,
            #     'ci_address': ci_address,
            #     'customer_name': company,
            #     'detailed_desc': inc['description'],
            #     'inc_number': inc['number'],
            #     'inc_sys_id': inc['sys_id'],
            #     'short_desc': inc['short_description'],
            #     'incident_state': inc['incident_state'],
            #     'service_name': service_name,
            #     'rec_short_desc': rec_short_desc,
            #     'rec_detailed_desc': rec_detailed_desc,
            #     'configuration_item_name': configuration_item_name
            # }
            # self._sensor_service.dispatch(trigger='ntt_itsm.win_service_check', payload=payload)

        #OpsRamp Agent offline
        elif (('opsramp agent is offline' in desc ) and ('wintel' in assign_group.lower() or 'intel' in assign_group.lower() or 'clarios-uscan fieldservice l2' in assign_group.lower() or 'clarios-uscan fieldservice l3'  in assign_group.lower())):
            insertto_datastore = "true"
            trigger_action = 'true'
            rec_short_desc = ''
            rec_detailed_desc = ''
            desc_org = inc['description']
            #Find_Before = self.beforeString(short_desc,'OpsRamp Agent service is offline')

            if configuration_item_name == '':
                ci_address = short_desc.split('-')[0]
                ci_address = ci_address.strip()
            else:
                ci_address = configuration_item_name

            trigger_action = 'true'
            if ('nttds-wintel global l1' in assign_group.lower() or 'clarios-uscan fieldservice l2' in assign_group.lower() or  'clarios-uscan fieldservice l3' in assign_group.lower()):
                trigger_action = 'true'
                support_group = self.get_support_group(inc)
            else:
                trigger_action = 'false'
            rec_short_desc = 'OpsRamp agent is offline'
            rec_detailed_desc = 'OpsRamp agent is offline'
            # self._logger.info('Already processing INC: ' + inc['number'] +'incident_open_at' + inc['opened_at'] )
            payload = {
                    'assignment_group': assign_group,
                    'ci_address': ci_address,
                    'customer_name': company,
                    'detailed_desc': inc['description'],
                    'inc_number': inc['number'],
                    'inc_sys_id': inc['sys_id'],
                    'os_type': 'windows',
                    'short_desc': inc['short_description'],
                    'configuration_item_name': configuration_item_name,
                    'rec_short_desc': rec_short_desc,
                    'rec_detailed_desc': rec_detailed_desc
                }
            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.win_monitoring_heartbeat_failure', payload=payload)
            else:
                insertto_datastore = "false"

        elif ('process stats' in short_desc_lower or 'opsramp agent is offline' in short_desc_lower) and ('unix' in assign_group.lower() or 'linux' in assign_group.lower()):
            insertto_datastore = "true"
            trigger_action = 'true'
            if 'clarios-unix global l1' in assign_group.lower():
                support_group = self.get_support_group(inc)
                if 'unix' in assign_group.lower():
                    trigger_action = 'true'
                else:
                    trigger_action = 'false'

            if 'opsramp agent is offline' in short_desc_lower:
                service = 'opsramp-agent'
            else:
                service = ""
                service_begin = desc_org.split('Process Name- ')[-1].replace('\n','').replace('\r','').strip()
                service = service_begin.split('Instance count')[0].strip().lower()
            
 
            payload = {
                'assignment_group': assign_group,
                'ci_address': ci_address,
                'customer_name': company,
                'detailed_desc': inc['description'],
                'inc_number': inc['number'],
                'inc_sys_id': inc['sys_id'],
                'os_type': 'linux',
                'short_desc': inc['short_description'],
                'service': service,
                'incident_state': inc['incident_state'],
                'configuration_item_name': configuration_item_name
            }
            if 'true' in trigger_action:
                self._sensor_service.dispatch(trigger='ntt_itsm.unix_process_alert', payload=payload)
            else:
                insertto_datastore = "false"

        return insertto_datastore

    def cleanup(self):
        pass

    def add_trigger(self, trigger):
        pass

    def update_trigger(self, trigger):
        pass

    def remove_trigger(self, trigger):
        pass
