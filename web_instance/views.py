# views.py
#
# Copyright (C) 2011-2018 Vas Vasiliadis
# University of Chicago
#
# Application logic for the GAS
#
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import uuid
import time
import json
from datetime import datetime

import boto3
from botocore.client import Config
from boto3.dynamodb.conditions import Key

from flask import (abort, flash, redirect, render_template,
  request, session, url_for)

from gas import app, db
from decorators import authenticated, is_premium
from auth import get_profile, update_profile

from botocore.client import ClientError
from io import BytesIO

# SET UP CONST VARIABLES
DIRECTORY = app.config['AWS_S3_KEY_PREFIX']
INPUT_BUCKET = app.config['AWS_S3_INPUTS_BUCKET']
RESULT_BUCKET = app.config['AWS_S3_RESULTS_BUCKET']
USER_TABLE = app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE']
AWS_REGION = app.config['AWS_REGION_NAME']
AWS_SNS_REQUEST = app.config['AWS_SNS_JOB_REQUEST_TOPIC']
DYNAMO_TABLE = app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE']


s3 = boto3.resource('s3')

"""Start annotation request
Create the required AWS S3 policy document and render a form for
uploading an annotation input file using the policy document
"""
@app.route('/annotate', methods=['GET'])
@authenticated
def annotate():
  # Open a connection to the S3 service
  s3 = boto3.client('s3',
    region_name=AWS_REGION,
    config=Config(signature_version='s3v4'))

  # bucket_name = INPUT_BUCKET
  user_id = session['primary_identity']

  # Generate unique ID to be used as S3 key (name)
  key_name = DIRECTORY + user_id + '/' + str(uuid.uuid4()) + '~${filename}'

  # Redirect to a route that will call the annotator
  redirect_url = str(request.url) + "/job"

  # Define policy conditions
  # NOTE: We also must inlcude "x-amz-security-token" since we're
  # using temporary credentials via instance roles
  encryption = app.config['AWS_S3_ENCRYPTION']
  acl = app.config['AWS_S3_ACL']
  expires_in = app.config['AWS_SIGNED_REQUEST_EXPIRATION']
  fields = {
    "success_action_redirect": redirect_url,
    "x-amz-server-side-encryption": encryption,
    "acl": acl
  }
  conditions = [
    ["starts-with", "$success_action_redirect", redirect_url],
    {"x-amz-server-side-encryption": encryption},
    {"acl": acl}
  ]

  # Generate the presigned POST call
  presigned_post = s3.generate_presigned_post(Bucket=INPUT_BUCKET,
    Key=key_name, Fields=fields, Conditions=conditions, ExpiresIn=expires_in)

  # Render the upload form which will parse/submit the presigned POST
  return render_template('annotate.html', s3_post=presigned_post)


"""Fires off an annotation job
Accepts the S3 redirect GET request, parses it to extract
required info, saves a job item to the database, and then
publishes a notification for the annotator service.
"""
@app.route('/annotate/job', methods=['GET'])
@authenticated
def create_annotation_job_request():
  # Extract the job ID from the S3 key

  # Persist job to database
  # Move your code here...

  # Send message to request queue
  # SET UP DB AND ANN TABLE
  dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
  ann_table = dynamodb.Table(DYNAMO_TABLE)

  # REQUEST PARAMETERS
  bucket_name = request.args.get('bucket')
  s3_key = request.args.get('key')
  etag = request.args.get('etag')

  ### DEBUGGING ####
  print(f"bucket name: {bucket_name} and key: {s3_key} and etag is: {etag}")

  # username and user-role
  user_name = session.get('primary_identity')
  profile = get_profile(identity_id=user_name)
  user_email, user_role = profile.email, profile.role

  # submit time
  current_time = int(time.time())
  submit_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time))

  # parsing
  uuid_filename = s3_key.rsplit('/', 1)[-1]
  uuid = uuid_filename.rsplit('~', 1)[0]
  filename = uuid_filename.rsplit('~', 1)[-1]

  # Create a job item and persist it to the annotations database
  data = {"job_id": uuid,
          "user_id": user_name,
          "input_file_name": filename,
          "s3_inputs_bucket": bucket_name,
          "s3_key_input_file": s3_key,
          "submit_time": submit_time,
          "job_status": "PENDING",
          "user_email": user_email,
          "user_role": user_role
          }
  try:
      dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
      ann_table = dynamodb.Table(DYNAMO_TABLE)
      ann_table.put_item(Item=data)
  except Exception as err:
      print (err)
      return jsonify({'code': 500,
                      'error':'(internal error) when adding item into s3 table'})
  # Try to publish a notification to my SNS arn
  try:
      client = boto3.client('sns', region_name='us-east-1')
      aws_arn = AWS_SNS_REQUEST
      message = json.dumps(data)
      response = client.publish(TopicArn=aws_arn, Message=message)
  except Exception as err:
      print (err)
      return jsonify({'code': 500,
                      'error':'(internal error) failed to make a notification/queue'})

  ### TESTING : between free_user vs. premium
  # update_profile(
  # identity_id=session['primary_identity'],
  # role="free_user"
  # )

  return render_template('annotate_confirm.html', job_id=uuid)


"""List all annotations for the user
"""
@app.route('/annotations', methods=['GET'])
@authenticated
def annotations_list():

  # Get list of annotations to display
  dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
  ann_table = dynamodb.Table(DYNAMO_TABLE)
  user_name = session.get('primary_identity')

  # get all jobs from dynamodb
  all_annotations = ann_table.query(
    IndexName='user_id_index',
    KeyConditionExpression=Key('user_id').eq(user_name)
    )

  return render_template('annotations.html', annotations=all_annotations['Items'])


"""Display details of a specific annotation job
"""
@app.route('/annotations/<id>', methods=['GET'])
@authenticated
def annotation_details(id):

  dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
  ann_table = dynamodb.Table(USER_TABLE)
  user_name = session.get('primary_identity')

  selected_job = ann_table.query(
    KeyConditionExpression=Key('job_id').eq(id)
    )

  ''' TESTING: To see if the selected job has archive id in dynamodb
  user_email = selected_job['Items'][0]['user_email']
  if 'results_file_archive_id' in selected_job['Items'][0]:
    print("YES :::: results_file_archive_id")
  else:
    print("NO :::: results_file_archive_id")
  '''

  try:
    # Get s3 results .annot.vcf file directory
    key_check = selected_job['Items'][0]['s3_key_result_file']

    # Get url with s3 key result file (.annot.vcf file)
    s3_url = boto3.client('s3', config=Config(signature_version='s3v4'))
    url = s3_url.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': RESULT_BUCKET,
            'Key': DIRECTORY + key_check
        }
    )
    profile = get_profile(identity_id=user_name)
    completion_time = int(selected_job['Items'][0]['complete_time'])
    current_time = int(time.time())

    # interval = app.config['FREE_USER_DATA_RETENTION']
    # NOW just for tesing :: 30 secdons, but later the interval should be 1800 sec (30 min)
    if (current_time - completion_time) <= 30:
      premium = True
    else:
      if selected_job['Items'][0]['user_role'] == 'free_user':
        premium = None
      else:
        premium = True
    completion_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(completion_time))
  except:
    premium = url = None
    completion_time = None

  return render_template('annotation_details.html', job=selected_job['Items'][0], complete = completion_time, url = url, premium = premium)


"""Display the log file for an annotation job
"""
@app.route('/annotations/<id>/log', methods=['GET'])
@authenticated
def annotation_log(id):

  dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
  ann_table = dynamodb.Table(USER_TABLE)
  user_name = session.get('primary_identity')

  selected_job = ann_table.query(
    KeyConditionExpression=Key('job_id').eq(id)
    )

  user_email = selected_job['Items'][0]['user_email']

  # Get s3 results file directory
  key_check = selected_job['Items'][0]['s3_key_log_file']

  # Get .count.log object as a string
  obj = s3.Object(RESULT_BUCKET, DIRECTORY + key_check)
  log = obj.get()["Body"].read().decode('utf-8').split('\n')

  return render_template('display_log.html', log = log)



"""Subscription management handler
"""
import stripe

@app.route('/subscribe', methods=['GET', 'POST'])
@authenticated
def subscribe():
  if request.method == "POST":
    # get token and stripe key
    token = request.form.get('stripe_token')
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
    cust = stripe.Customer.create(
            description="New customer" + session['primary_identity'],
            source = token
            )
    # update the user profile value from free to premium
    update_profile(
      identity_id=session['primary_identity'],
      role="premium_user"
      )

    # dynamodb query
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    ann_table = dynamodb.Table(DYNAMO_TABLE)
    user_name = session.get('primary_identity')

    # accessing all jobs that belong to the current user
    all_annotations = ann_table.query(
      IndexName='user_id_index',
      KeyConditionExpression=Key('user_id').eq(user_name)
    )

    # as soon as an user subcribes to premium, the value of user role should be premium_user
    for item in all_annotations['Items']:
      job_id = item['job_id']
      role_update = {'user_role': {'Value': "premium_user",
                                   'Action': 'PUT'}}
      ann_table.update_item(Key = {'job_id':job_id},
                            AttributeUpdates = role_update)

    return render_template('subscribe_confirm.html', stripe_id=cust.id)

  return render_template('subscribe.html')

"""DO NOT CHANGE CODE BELOW THIS LINE
*******************************************************************************
"""

"""Home page
"""
@app.route('/', methods=['GET'])
def home():
  return render_template('home.html')

"""Login page; send user to Globus Auth
"""
@app.route('/login', methods=['GET'])
def login():
  app.logger.info('Login attempted from IP {0}'.format(request.remote_addr))
  # If user requested a specific page, save it to session for redirect after authentication
  if (request.args.get('next')):
    session['next'] = request.args.get('next')
  return redirect(url_for('authcallback'))

"""404 error handler
"""
@app.errorhandler(404)
def page_not_found(e):
  return render_template('error.html',
    title='Page not found', alert_level='warning',
    message="The page you tried to reach does not exist. Please check the URL and try again."), 404

"""403 error handler
"""
@app.errorhandler(403)
def forbidden(e):
  return render_template('error.html',
    title='Not authorized', alert_level='danger',
    message="You are not authorized to access this page. If you think you deserve to be granted access, please contact the supreme leader of the mutating genome revolutionary party."), 403

"""405 error handler
"""
@app.errorhandler(405)
def not_allowed(e):
  return render_template('error.html',
    title='Not allowed', alert_level='warning',
    message="You attempted an operation that's not allowed; get your act together, hacker!"), 405

"""500 error handler
"""
@app.errorhandler(500)
def internal_error(error):
  return render_template('error.html',
    title='Server error', alert_level='danger',
    message="The server encountered an error and could not process your request."), 500

### EOF
