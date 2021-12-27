# Alexa Smart Home Skill for BoilerIO

BoilerIO is an open-source thermostat designed to control heating in your home.
This Alexa smart home skill lets you use voice control via Alexa to control it
hands free.

## What can it do?

> Alexa, set upstairs thermostat to 20 degrees

> Alexa, what's the upstairs tempature?

> Alexa, make it warmer

## Setting up the skill

Since this is not a "released" skill (because it currently requires custom
configuration for your backend deployment), you will need to deploy it to your
account and manage it yourself.

You will first need a working BoilerIO setup, a working AWS CLI and `sam`
installation locally, an AWS account to deploy to, and an Alexa developer account.  Setting it up takes two steps:

1. Create a client secret and add it to your BoilerIO setup
1. Configure the Alexa skill
1. Set up the lambda function

### Create client secret

The client secret is used to allow authentication using an access key rather
than an ID token.  Only the Alexa (or other trusted) client should be configured
to use a client secret to enable this feature.  You can generate a client secret
using any way of producing a random string, e.g. a random UUID (`uuidgen -r` on
Linux) and insert it into the client secrets table:

```sql
INSERT INTO clientsecrets VALUES ('foo');
```

### Configure the Alexa skill

In the Alexa developer console, create a Smart Home skill.  You will need the
skill ID later.  For authentication, you will need to create credentials in the
[Google developer console](https://console.cloud.google.com/apis), add the
Alexa-provided redirect URLs, and then add the client ID and secret in the Alexa
skills configuration.  For the lambda function, you can put a temporary ARN in
even if it doesn't yet exist, or use the ARN of the function you'll create in
the next step.  The function will be called `boilerio-amart-home-skill`, and the
ARN format is `arn:aws:lambda:<ISO region code>:<account
number>:function:boilerio-smart-home-skill`.

### Lambda function/AWS setup

Run `sam build`/`sam deploy` to deploy to your account.  This will prompt you
with updates that will be made, which includes creating the Lambda function and
IAM invocation role.  The settings are saved in a toml file similar to this:

```
version = 0.1
[default]
[default.deploy]
[default.deploy.parameters]
stack_name = "boilerio-skill"
s3_bucket = "aws-sam-cli-managed-default-samclisourcebucket-..."
s3_prefix = "boilerio-skill"
region = "eu-west-1"
confirm_changeset = true
capabilities = "CAPABILITY_IAM"
parameter_overrides = "SkillId=\"...\" BoilerIOBaseURL=\"...\" BoilerIOClientSecret=\"...\""
```