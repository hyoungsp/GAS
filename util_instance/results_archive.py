import uuid
import subprocess
import os
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr
import boto3
from botocore.client import Config
import sys
from flask import session
import time

from config import Config

###############################################################################
############ HYOUNGSUN PARK CAPSTONE PYTHON ARCHIVE SCRIPT ####################
###############################################################################

config = Config()

REGION = config.AWS_REGION_NAME

AWS_GLACIER_VAULT = config.AWS_GLACIER_VAULT
AWS_SQS_RESULT_ARCHIVE_NAME = config.AWS_SQS_ARCHIVE
AWS_S3_RESULTS_BUCKET = config.AWS_S3_RESULTS_BUCKET
AWS_DYNAMODB_ANNOTATIONS_TABLE = config.AWS_DYNAMODB_ANNOTATIONS_TABLE

max_number_of_messages = 10
long_polling_wait_time_seconds = 20
#FREE_USER_DATA_RETENTION = config.FREE_USER_DATA_RETENTION
FREE_USER_DATA_RETENTION = 30 #### JUST FOR NOW: SET UP 30 sec


def check_user_role():
    """Read messages from the SQS queue that is subscribed to the
    SNS Topic "jaeyeun_results_archive" (via long polling),
    checks whether the user_role is free or premium. If the user
    hasn't upgraded to premium within 30 minutes of completion time,
    the annotation job result (result object) is deleted from S3
    Results Bucket and is uploaded into Glacier.
    """
    try:
        #Connect to SQS queue
        print(f'Connecting to SQS queue: {AWS_SQS_RESULT_ARCHIVE_NAME}')
        sqs = boto3.resource('sqs', region_name=REGION)
        queue = sqs.get_queue_by_name(QueueName=AWS_SQS_RESULT_ARCHIVE_NAME)
    except Exception as e:
        return 'Error: Failed to connect to SQS:\n{}'.format(e)
    print('Long polling wait time: {} seconds'.format(long_polling_wait_time_seconds))
    while True:
        messages = queue.receive_messages(
            MaxNumberOfMessages=max_number_of_messages,
            WaitTimeSeconds=long_polling_wait_time_seconds
            )
        print("********** Waiting for moving annot file to Glacier Vault ************")
        if len(messages) > 0:
            for message in messages:
                msg_body = eval(eval(message.body)['Message'])
                print(">>>>>>>>>MSG")
                print(msg_body)

                job_id = msg_body['job_id']
                # extract user_role
                user_role = msg_body['user_role']
                # extract s3_key_result_file
                s3_key_result_file = msg_body['s3_key_result_file']
                s3_key_result_file = 'hyoungsun/' + s3_key_result_file
                # extract complete time
                print("****************")
                print(s3_key_result_file)
                complete_time = int(msg_body['complete_time'])
                current_time = int(time.time())
                time_elapsed = current_time - complete_time
                # if time_elapsed <= FREE_USER_DATA_RETENTION:
                #     message.delete()
                if time_elapsed > FREE_USER_DATA_RETENTION:
                    if 'premium' in user_role:
                        message.delete()
                    else:
                        print("********* ABOUT TO REMOVE RESULT FILE ************")
                        results_file_archive_id = upload_to_glacier(s3_key_result_file)
                        update_dynamodb_glacier_id(job_id, results_file_archive_id)
                        delete_object_from_s3(s3_key_result_file)
                        message.delete()
                        print("********** The result file has been transferred ************")
                else:
                    pass

def upload_to_glacier(s3_key_result_file):
    """Upload object to Glacier to archive.
    """
    s3 = boto3.resource('s3',region_name=REGION)
    result_file = s3.Object(AWS_S3_RESULTS_BUCKET, s3_key_result_file)
    result_file = result_file.get()['Body'].read()
    glacier = boto3.client('glacier', region_name=REGION)
    results_file_archive_id = glacier.upload_archive(vaultName=AWS_GLACIER_VAULT,body=result_file)
    print('RESULTS FILE UPLOADED TO GLACIER ARCHIVE')
    return results_file_archive_id

def delete_object_from_s3(s3_key_result_file):
    """Delete object from S3 results bucket.
    """
    s3 = boto3.client('s3', region_name=REGION)
    s3.delete_object(Bucket=AWS_S3_RESULTS_BUCKET, Key=s3_key_result_file)
    print('DELETED RESULT FILE FROM S3 RESULTS BUCKET')

def update_dynamodb_glacier_id(job_id, results_file_archive_id):
    """Persist glacier id to the dynamodb.
    """
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    ann_table = dynamodb.Table(AWS_DYNAMODB_ANNOTATIONS_TABLE)
    # update dynamo db with glacier id
    attribute_updates = {
        'results_file_archive_id':{'Value': results_file_archive_id['archiveId'], 'Action': 'PUT'}
        }
    ann_table.update_item(
        Key={'job_id': job_id},
        AttributeUpdates=attribute_updates
        )
    print('UPDATED DYNAMODB: PERSIST GLACIER ARCHIVE ID')

def main():
    check_user_role()

if __name__ == '__main__':
    sys.exit(main())
