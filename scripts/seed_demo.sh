#!/usr/bin/env bash
set -euo pipefail

docker compose -f deploy/docker-compose.yml run --rm api python manage.py shell -c "
from inventory.models import Location, Container
from samples.models import Sample
from custom_fields.models import FieldDefinition, FieldValue

# Location
loc, _ = Location.objects.get_or_create(name='Freezer A', defaults={'kind':'freezer'})

# Container
cont, _ = Container.objects.get_or_create(container_id='C-001', defaults={'kind':'box', 'location': loc})

# Sample
s, _ = Sample.objects.get_or_create(sample_id='S-001', defaults={'status':'RECEIVED', 'container': cont})

# Custom field definition
fd, _ = FieldDefinition.objects.get_or_create(
    entity_type='Sample',
    name='patient_id',
    defaults={'label':'Patient ID', 'data_type':'string', 'required': False, 'rules': {}}
)

# Custom field value
fv, _ = FieldValue.objects.get_or_create(
    field_definition=fd,
    entity_type='Sample',
    entity_id=str(s.id),
    defaults={'value':'P-12345'}
)

print('Seeded demo data:')
print(' Location:', loc.id, loc.name)
print(' Container:', cont.id, cont.container_id)
print(' Sample:', s.id, s.sample_id)
print(' FieldDefinition:', fd.id, fd.name)
print(' FieldValue:', fv.id, fv.value)
"
