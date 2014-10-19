# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

from celery import shared_task
from celery.utils.log import get_task_logger
from celery import current_task

from lxml import etree

from django.utils.timezone import now, make_aware, make_naive, UTC
from datetime import timedelta

from oaipmh.client import Client
from oaipmh.metadata import MetadataRegistry, oai_dc_reader
from oaipmh.datestamp import tolerant_datestamp_to_datetime
from oaipmh.error import DatestampError, NoRecordsMatchError

from oai.models import *
from oai.settings import *

logger = get_task_logger(__name__)

@shared_task
def fetch_from_source(pk):
    source = OaiSource.objects.get(pk=pk)
    format, created = OaiFormat.objects.get_or_create(name=metadata_format) # defined in oai.settings
    #try:
    # Set up the OAI fetcher
    registry = MetadataRegistry()
    registry.registerReader(format.name, oai_dc_reader)
    client = Client(source.url, registry)
    client.updateGranularity()

    # Limit queries to records in a time range of 7 days
    time_chunk = query_time_range

    start_date = make_naive(source.last_update, UTC())
    current_date = make_naive(now(), UTC())
    until_date = start_date + time_chunk

    while start_date <= current_date:
        try:
            listRecords = client.listRecords(metadataPrefix=format.name, from_=start_date, until=until_date)
        except NoRecordsMatchError:
            listRecords = []

        for record in listRecords:
            update_record(source, record, format)

        source.last_update = make_aware(min(until_date, current_date), UTC())
        source.save()
        until_date += time_chunk
        start_date += time_chunk
        #except Exception as e:
    #    error = OaiError(source=source, text=unicode(e))
    #    error.save()

@shared_task
def fetch_sets_from_source(pk):
    source = OaiSource.objects.get(pk=pk)
    registry = MetadataRegistry()
    client = Client(source.url, registry)
    
    listSets = client.listSets()
    for set in listSets:
        s, created = OaiSet.objects.get_or_create(source=source, name=set[0])
        s.fullname=set[1]
        s.save()

@shared_task
def fetch_formats_from_source(pk):
    source = OaiSource.objects.get(pk=pk)
    registry = MetadataRegistry()
    client = Client(source.url, registry)
    
    listFormats = client.listMetadataFormats()
    for format in listFormats:
        f, created = OaiFormat.objects.get_or_create(name=format[0])
        f.schema=format[1]
        f.namespace=format[2]
        f.save()


def update_record(source, record, format):
    fullXML = record[1].element()
    metadataStr = etree.tostring(fullXML, pretty_print=True)
    identifier = record[0].identifier()
    timestamp = record[0].datestamp()
    timestamp = make_aware(timestamp, UTC())

    modelrecord, created = OaiRecord.objects.get_or_create(identifier=identifier, format=format,
            defaults={'source':source, 'metadata':metadataStr, 'timestamp':timestamp})
    if not created:
        modelrecord.timestamp = timestamp
        modelrecord.metadata = metadataStr
        modelrecord.save()

    # Add regular sets
    for s in record[0].setSpec():
        modelset, created = OaiSet.objects.get_or_create(source=source, name=s)
        modelrecord.sets.add(modelset)

    # Apply virtual set extractors
    for extractor in extractors:
        if extractor.format() == format.name:
            sets = extractor.getVirtualSets(fullXML)
            for set in sets:
                name = extractor.subset()+':'+set
                modelset, created = OaiSet.objects.get_or_create(name=name)
                modelrecord.sets.add(modelset)


@shared_task
def cleanup_resumption_tokens():
    threshold = now() - resumption_token_validity
    ResumptionToken.objects.filter(date_created__lt=threshold).delete()



