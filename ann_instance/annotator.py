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


###############################################################################
############ HYOUNGSUN PARK CAPSTONE PYTHON ANNOTATOR SCRIPT ##################
###############################################################################

def main():
    # attribute: http://boto3.readthedocs.io/en/latest/guide/sqs.html
    print("running the annotator.py !!")
    sqs = boto3.resource('sqs', region_name='us-east-1')
    # Obtaining SQS.Queue instance with my own queue name: 'hyoungsun_job_requests'
    queue = sqs.get_queue_by_name(QueueName='hyoungsun_job_requests')

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
            s3_inputs_bucket = msg_contents["s3_inputs_bucket"]
            s3_key_input_file = msg_contents["s3_key_input_file"]
            submit_time = msg_contents["submit_time"]
            user_email = msg_contents["user_email"]

            # Create a unique folder path (directory)
            # folderpath = "Capstone_data/" + username + "/" + job_id
            folderpath = username + "/" + user_email + "/" + job_id
            file_directory = folderpath + "/" + input_file_name
            try:
                os.makedirs(folderpath)
            except OSError as err:
                print (err)

            print("(annotator.py) s3_key_input_file: " + s3_key_input_file)

            # Download the file to annotate subprocess
            s3 = boto3.resource('s3', region_name='us-east-1')
            s3.Bucket(s3_inputs_bucket).download_file(s3_key_input_file, file_directory)


            # annotate the file
            try:
                subprocess.Popen(['python', 'run.py', file_directory, s3_key_input_file, job_id])
            except Exception as err:
                return jsonify({'code': 500,
                                'error': 'Annotate failed (internal server error)'})

            # Update the back-end database (dynamodb) if the current job status is 'PENDING'
            dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
            ann_table = dynamodb.Table('hyoungsun_annotations')
            ann_table.update_item(
                Key={
                    'job_id': job_id
                },
                ConditionExpression='job_status = :old_status',
                UpdateExpression='SET job_status = :status',
                ExpressionAttributeValues={
                    ':old_status': 'PENDING',
                    ':status': 'RUNNING'
                }
            )

            # Delete the message from the queue, once the annotated job has been successfully submitted
            message.delete()
            print('Message has been deleted.......')


if __name__ == "__main__":
    main()
