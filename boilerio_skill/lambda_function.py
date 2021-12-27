import os
import json
import logging
import datetime
from uuid import uuid4

import requests

BASE_URL = os.environ.get("BASE_URL")

USER_ENDPOINT = BASE_URL + '/me'
ZONES_ENDPOINT = BASE_URL + '/zones'

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

def mk_response_header(correlationToken: str):
    return {
        "namespace": "Alexa",
        "name": "Response",
        "messageId": str(uuid4()),
        "correlationToken": correlationToken,
        "payloadVersion": "3"
    }


def get_authorized_session(access_token):
    session = requests.Session()
    client_secret = os.environ['CLIENT_SECRET']
    r = session.post(USER_ENDPOINT, data={
        'access_token': access_token,
        'client_secret': client_secret
    }, headers={'X-Requested-With': 'python-requests'})
    if r.status_code != 200:
        logger.debug(r.content)
        raise ValueError("Couldn't authorize")
    return session


def handle_discover(request, session):
    # Generate a temperature sensor for each zone:
    r = session.get(ZONES_ENDPOINT + '/')
    zones = r.json()
    logger.debug(zones)

    endpoints = []
    for zone in zones:
        endpoints.append({
            "endpointId": str(zone['zone_id']),
            "manufacturerName": "BoileriIO",
            "description": "Zone sensor",
            "friendlyName": zone['name'] + " thermostat",
            "displayCategories": ['THERMOSTAT'],
            "capabilities": [
                {
                    "type": "AlexaInterface",
                    "interface": "Alexa.ThermostatController",
                    "version": "3",
                    "properties": {
                        "supported": [
                            {
                                "name": "targetSetpoint"
                            },
                        ],
                        "proactivelyReported": False,
                        "retrievable": True,
                    },
                    "configuration": {
                        "supportedModes": ["HEAT"],
                        "supportsScheduling": True,
                    }
                },
                {
                    "type": "AlexaInterface",
                    "interface": "Alexa.TemperatureSensor",
                    "version": "3",
                    "properties": {
                        "supported": [
                            {
                                "name": "temperature"
                            }
                        ],
                    "proactivelyReported": False,
                    "retrievable": True,
                }
            },
            ]
        })

    response = {
            "event": {
                "header": {
                  "namespace": "Alexa.Discovery",
                  "name": "Discover.Response",
                  "payloadVersion": "3",
                  "messageId": str(uuid4()),
                },
                "payload": {
                    "endpoints": endpoints
                }
            }
        }

    logger.debug("Discovery response: " + json.dumps(response))
    return response


def fetch_zone_state(zone_id, session):
    state_endpoint = ZONES_ENDPOINT + "/%s/reported_state" % zone_id
    r = session.get(state_endpoint)
    return r.json()


def fetch_zone_override(zone_id, session):
    state_endpoint = ZONES_ENDPOINT + "/%s/override" % zone_id
    r = session.get(state_endpoint)
    return r.json() if r.status_code == 200 else None


def get_zone_properties(zone_id, session):
    state = fetch_zone_state(zone_id, session)
    override = fetch_zone_override(zone_id, session)
    zone_properties = state_to_zone_properties(state, override)
    return zone_properties


def state_to_error_response(state):
    """Return None if the zone is OK, otherwise return an ErrorResponse."""
    if state['state'] == 'Stale':
        return {
            'type': 'ENDPOINT_UNREACHABLE',
            'message': ''
        }
    return None


def state_to_zone_properties(state, override):
    now = datetime.datetime.utcnow().isoformat() + 'Z'

    # Use the override the user requested rather than what the endpoint has
    # picked up to make the interaction more reasonable.
    targetSetpoint = override['temp'] if override else state['target']
    return [
        {
            "namespace": "Alexa.ThermostatController",
            "name": "thermostatMode",
            "value": "HEAT",
            "timeOfSample": now,
            "uncertaintyInMilliseconds": 1000,
        },
        {
            "namespace": "Alexa.TemperatureSensor",
            "name": "temperature",
            "value": {
                "value": round(state['current_temp'], 1),
                "scale": "CELSIUS"
            },
            "timeOfSample": now,
            "uncertaintyInMilliseconds": 1000
        },
        {
            "namespace": "Alexa.ThermostatController",
            "name": "targetSetpoint",
            "value": {
                "value": targetSetpoint,
                "scale": "CELSIUS"
            },
            "timeOfSample": now,
            "uncertaintyInMilliseconds": 500
        },
        {
            "namespace": "Alexa.EndpointHealth",
            "name": "connectivity",
            "value": {
                "value": "UNREACHABLE" if state['state'] == 'Stale' else "OK"
            },
            "timeOfSample": now,
            "uncertaintyInMilliseconds": 0
        }
    ]


def handle_statereport(request, session):
    # The endpoint ID is a zone:
    endpoint = request['directive']['endpoint']['endpointId']
    state = fetch_zone_state(endpoint, session)
    override = fetch_zone_override(endpoint, session)
    zone_properties = state_to_zone_properties(state, override)
    error_response = state_to_error_response(state)

    response = {
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "StateReport" if not error_response else "ErrorResponse",
                "messageId": str(uuid4()),
                "correlationToken": request['directive']['header']['correlationToken'],
                "payloadVersion": "3",
            },
            "endpoint": {
                "endpointId": endpoint,
            },
            "payload": {} if not error_response else error_response
        },
        "context": {
            "properties": zone_properties,
        }
    }

    logger.debug("ReportState response: " + json.dumps(response))
    return response


def handle_adjust_temperature(request, session):
    setpointDelta = request['directive']['payload']['targetSetpointDelta']['value']
    # XXX should verify it's in Celcius.

    # Get the current target.  It's the override if set, otherwise use the
    # reported target
    endpoint = request['directive']['endpoint']['endpointId']
    state = fetch_zone_state(endpoint, session)
    override = fetch_zone_override(endpoint, session)
    currentTarget = override['temp'] if override else state['target']
    updated_target = currentTarget + setpointDelta
    override = {'temp': updated_target, 'hours': 3, 'mins': 0}
    override_url = ZONES_ENDPOINT + '/%s/override' % endpoint

    # XXX check success:
    r = session.post(override_url, data=override, headers={"X-Requested-With": "python-requests"})
    logger.debug(r.content)

    # Return state, replacing target with the one that was just set:
    zone_properties = get_zone_properties(endpoint, session)
    response = {
        "event": {
            "header": mk_response_header(request['directive']['header']['correlationToken']),
            "endpoint": {
                "endpointId": endpoint,
            },
            "payload": {}
          },
        "context": {
            "properties": zone_properties
        }
    }
    logger.debug("AdjustTargetTemperature response: " + json.dumps(response))
    return response


def handle_set_temperature(request, session):
    # The endpoint ID is a zone:
    endpoint = request['directive']['endpoint']['endpointId']
    target = request['directive']['payload']['targetSetpoint']['value']

    # Seconds can be specified but we're ignoring it because the
    # service doesn't support it.
    if 'schedule' in request['directive']['payload']:
        duration = request['directive']['payload']['schedule']['duration']
        assert duration.startswith("PT")
        duration = duration[2:]
        hours = 0
        if 'H' in duration:
            h = duration.find('H')
            hours = int(duration[:h])
            duration = duration[h+1:]
        mins = 0
        if 'M' in duration:
            m = duration.find('M')
            mins = int(duration[:m])
            duration = duration[m+1:]
    else:
        hours = 3
        mins = 0

    override = {'temp': target, 'hours': hours, 'mins': mins}
    override_url = ZONES_ENDPOINT + '/%s/override' % endpoint

    # XXX check success:
    r = session.post(override_url, data=override, headers={"X-Requested-With": "python-requests"})
    logger.debug(r.content)

    # Return state, replacing target with the one that was just set:
    zone_properties = get_zone_properties(endpoint, session)
    response = {
        "event": {
            "header": mk_response_header(request['directive']['header']['correlationToken']),
            "endpoint": {
                "endpointId": endpoint,
            },
            "payload": {}
          },
        "context": {
            "properties": zone_properties
        }
    }
    logger.debug("SetTargetTemperature response: " + json.dumps(response))
    return response


def handle_resume_schedule(request, session):
    # The endpoint ID is a zone:
    endpoint = request['directive']['endpoint']['endpointId']
    override_url = ZONES_ENDPOINT + '/%s/override' % endpoint

    # Clear any active overrides:
    # XXX error handling:
    session.delete(override_url)
    
    # Return state:
    zone_properties = get_zone_properties(endpoint, session)
    response = {
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "Response",
                "messageId": str(uuid4()),
                "correlationToken": request['directive']['header']['correlationToken'],
                "payloadVersion": "3"
            },
            "endpoint": {
                "endpointId": endpoint,
            },
            "payload": {}
          },
        "context": {
            "properties": zone_properties
        }
    }
    return response


def handle_set_mode(request, session):
    target_mode = request['directive']['payload']['thermostatMode']['value']
    endpoint = request['directive']['endpoint']['endpointId']
    zone_properties = get_zone_properties(endpoint, session)

    response = {
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "Response",
                "messageId": str(uuid4()),
                "correlationToken": request['directive']['header']['correlationToken'],
                "payloadVersion": "3"
            },
            "endpoint": {
                "endpointId": endpoint,
            },
            "payload": {}
          },
        "context": {
            "properties": zone_properties
        }
    }
    
    if target_mode != 'HEAT':
        # Other modes not currently supposrted, create an error response.
        response['event']['header']['name'] = 'ErrorResponse'
        response['event']['payload'] = {
            'type': 'UNSUPPORTED_THERMOSTAT_MODE',
            'message': 'BoilerIO only supports Heating mode'
        }
    return response

def lambda_handler(request, context):
    logger.debug(json.dumps(request))
    
    directive = request['directive']

    # Handle discovery requests
    if directive['header']['name'] == 'Discover':
        logger.debug("Handling discover")
        payload = directive['payload']
        access_token = payload['scope']['token']
        session = get_authorized_session(access_token)
        return handle_discover(request, session)

    # Handle directives:
    # In directives, the auth information is in the endpoint object:
    if 'endpoint' in directive:
        endpoint = directive['endpoint']
        access_token = endpoint['scope']['token']
        session = get_authorized_session(access_token)
        logger.debug("Authorized")

    handlers = {
        'ReportState': handle_statereport,
        'SetTargetTemperature': handle_set_temperature,
        'ResumeSchedule': handle_resume_schedule,
        'SetThermostatMode': handle_set_mode,
        'AdjustTargetTemperature': handle_adjust_temperature,
    }
    directive_name = directive['header']['name']
    if directive_name in handlers:
        logger.debug("Handling directive %s", directive_name)
        handler = handlers[directive_name]
        return handler(request, session)
    else:
        logger.error("Couldn't handle directive: %s", directive_name)

    # TODO: error handling
    return
