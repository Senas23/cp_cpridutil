#!/usr/bin/env python3
"""
This sccript will pull all SMB gateways and run calls to retreive the versions
and other details from the gateways to a csv file.
"""

import argparse
import logging
import sys
import csv
import base64
import re

from cpapi import APIClient, APIClientArgs
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

def banner():
  logo = \
    """
    +-+-+-+-+-+-+-+-+-+-+
    |C|P|r|i|d| |U|t|i|l|
    +-+-+-+-+-+-+-+-+-+-+

    By: The Machine & API Guy & KJ
    """
  print(logo)
    
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", default="admin")
    parser.add_argument("-p", "--password", default="")
    parser.add_argument("-m", "--management", default="")
    parser.add_argument("--port", default=443)
    parser.add_argument("-d", "--domain", default="")

    parser.add_argument("-o",
                        "--outputfile",
                        help="Output file",
                        type=argparse.FileType("w"),
                        default="output.csv")
    parsed_args = parser.parse_args()

    client_args = APIClientArgs(server=parsed_args.management, port=parsed_args.port)

    with APIClient(client_args) as client:

        login = client.login(username=parsed_args.username, password=parsed_args.password, domain=parsed_args.domain)
        if login.success:
            log.info("login succeeded")
        else:
            log.error(login.error_message)
            sys.exit(1)
            
        def get_all_items(command, parameters={}, limit=500) -> list:
          items = []
          payload = {"details-level": "full", "limit": limit, "offset": 0}
          payload.update(parameters)
          response = client.api_call(command, payload=payload).data
          items.extend(response["objects"])
          for offset in range(limit, response['total'], limit):
            payload['offset'] = offset
            response = client.api_call(command, payload=payload).data
            items.extend(response["objects"])
          return items
        
        def get_smb_gateways(gateways) -> list:
          return [gw for gw in gateways 
                  if "operating-system" in gw and gw.get("operating-system") == "Gaia Embedded"]
        # Change 
        def get_mgmt_name(gateways):
          for gw in gateways:
            if "management-blades" in gw and len(gw["management-blades"]) > 0:
              if gw["management-blades"]["network-policy-management"] == True and \
                gw["management-blades"]["secondary"] == False:
                return gw.get("name")

        gateways = get_all_items(command="show-gateways-and-servers")
        
        smb_gateways = get_smb_gateways(gateways)
        mgmt_name = get_mgmt_name(gateways)

        output_details = []

        # Add LSM managed GWs through API
        lsm_gateways = get_all_items(command="show-objects", parameters={"type": "lsm-gateway"})
        for gw in lsm_gateways:
          if "os-name" in gw and gw.get("os-name") == "Small Office Appliance":
            gw_details = {'name': gw['name'], 'ipaddress': gw['ip-address'] }
            output_details.append(gw_details)

        # Add SMB devices 
        for item in smb_gateways:
            gw_details = { 'name': item['name'], 'ipaddress': item['ipv4-address'] }
            output_details.append(gw_details)

        if len(output_details) == 0:
            print("No GWs found, exit!")
            exit(0)

        command = "clish -c 'show diag'"
        rows = []
        for gw in output_details:
          row = []
          run_script = client.api_call("run-script", payload={
              "script-name": f"Getting firmware data from {gw['name']}",
              "script": f"$CPDIR/bin/cprid_util \
                -server {gw['ipaddress']} \
                -verbose rexec \
                -rcmd bash -c \"{command}\"",
              "targets": [mgmt_name]
          }).data
          image = "N/A"
          serial = "N/A"
          mac = "N/A"
          status = "Failed"
          
          try:
            if run_script['tasks'][0]['status'] == "succeeded":
                output_list = base64.b64decode(
                    run_script['tasks'][0]['task-details'][0]['responseMessage']).decode('ascii').splitlines()
                r = re.compile(r'(?:(Current )?[Ii]mage name|Serial|HW MAC)')
                tmp_output = list(filter(r.match, output_list))
                # Comprehention on List check for CONTAINS
                tmp_image, *_ = [k for k in tmp_output if "name" in k]
                image = tmp_image.split(':', 1)[1].strip()
                try:
                    tmp_serial, *_ = [k for k in tmp_output if "Serial" in k]
                    serial = tmp_serial.split(':', 1)[1].strip()
                except Exception:
                    pass
                tmp_mac, *_ = [k for k in tmp_output if "MAC" in k]
                mac = tmp_mac.split(':', 1)[1].strip()
                status = "Successful"
            else:
                print(f"Could not reach GW IP: {gw['ipaddress']}")
          except Exception:
            pass
          finally:
            row = [ gw['name'], image, serial, mac, gw['ipaddress'], status ]
            rows.append(row)
            print(row)
          
          write_header = ['GW', 'Image', 'Serial', 'MAC', 'IP', 'Status']
          write = csv.writer(parsed_args.outputfile, lineterminator='\n')
          write.writerow(write_header)
          write.writerows(rows)
            
            
if __name__ == "__main__":
    banner()
    main()
