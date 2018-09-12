import uuid
import json
import os
import shutil
import os.path
from os import path
import subprocess
from shutil import copyfile
from flask import Flask, request, Response, jsonify
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr
from config import Config

###############################################################################
############ HYOUNGSUN PARK CAPSTONE PYTHON RESULTS SCRIPT ####################
###############################################################################

config = Config()

def send_email_ses(recipients=None, sender=None, subject=None, body=None):

    region = config.AWS_REGION_NAME
    ses = boto3.client('ses', region_name=region)
    response = ses.send_email( Destination = {'ToAddresses': recipients},
                               Message={'Body': {'Text': {'Charset': "UTF-8", 'Data': body}},
                                        'Subject': {'Charset': "UTF-8", 'Data': subject},}, Source=sender)
    return response['ResponseMetadata']['HTTPStatusCode']

def main():
    # attribute: http://boto3.readthedocs.io/en/latest/guide/sqs.html
    sqs = boto3.resource('sqs', region_name='us-east-1')
    # Obtaining SQS.Queue instance with my own queue name: 'hyoungsun_job_requests'
    queue = sqs.get_queue_by_name(QueueName='hyoungsun_job_results')

    while True:
        # Trying to read a message from the queue (without waiting/pausing) using long polling
        print(".....requesting SQS for a message right now ...")
        messages = queue.receive_messages(MaxNumberOfMessages=1, WaitTimeSeconds=20)

        if len(messages) > 0:
            print(".....just received 1 message....")
            message = messages[0]
            msg_contents = eval(eval(message.body)['Message'])

            # parse the parameters of message body

            job_id = msg_contents["job_id"]
            username = msg_contents["user_id"]
            input_file_name = msg_contents["input_file_name"]
            s3_results_bucket = msg_contents["s3_results_bucket"]
            submit_time = msg_contents["submit_time"]
            complete_time = msg_contents["complete_time"]
            recipients = msg_contents["user_email"]

            notification = {"job_id": job_id,
                            "user_id": username,
                            "input_file_name": input_file_name,
                            "s3_results_bucket": s3_results_bucket,
                            "submit_time": submit_time,
                            "complete_time": complete_time}

            GAS_notification = json.dumps(notification)

            try:
                send_email_ses(recipients = [recipients], sender = "hyoungsun@ucmpcs.org", subject = "GAS Job:" + job_id, body = GAS_notification)


            except Exception as err:
                return jsonify({'code': 500,
                                'error': 'Annotate failed (internal server error)'})

            message.delete()
            print('Message has been deleted.......')

if __name__ == "__main__":
    main()
