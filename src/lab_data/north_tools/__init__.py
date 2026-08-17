from nomad.config.models.north import NORTHTool
from nomad.config.models.plugins import NORTHToolEntryPoint

lab_analysis = NORTHTool(
    short_description='Jupyter Notebook server in NOMAD NORTH for NOMAD plugin lab-data.',
    image='ghcr.io/ylylyl98/lab-data:main',
    description='Jupyter Notebook server in NOMAD NORTH for NOMAD plugin lab-data.',
    external_mounts=[],
    file_extensions=['ipynb'],
    icon='logo/jupyter.svg',
    image_pull_policy='Always',
    default_url='/lab',
    maintainer=[{'email': 'commonlab02@gmail.com', 'name': 'ShiLabCMU'}],
    mount_path='/home/jovyan',
    path_prefix='lab/tree',
    privileged=False,
    with_path=True,
    display_name='Lab Analysis',
)

north_entry_point = NORTHToolEntryPoint(
    id_url_safe='lab-data-lab-analysis',
    north_tool=lab_analysis,
)