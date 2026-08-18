from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.annotations import (
    BrowserAnnotation,
    ELNAnnotation,
    ELNComponentEnum,
)
from nomad.metainfo import MEnum, MSection, Quantity, SchemaPackage, Section, SubSection

m_package = SchemaPackage()


class GateValue(MSection):
    m_def = Section(label='Gate Value')

    gate = Quantity(type=str)
    voltage = Quantity(type=float, unit='V')


class GateTerm(MSection):
    m_def = Section(label='Gate Term')

    node = Quantity(type=str)
    coefficient = Quantity(type=float)


class GateConstraint(MSection):
    m_def = Section(label='Gate Constraint')

    raw_expression = Quantity(type=str)
    control_mode = Quantity(type=str)
    constant = Quantity(type=float)
    terms = SubSection(sub_section=GateTerm.m_def, repeats=True)


class ElectricalConnection(MSection):
    m_def = Section(label='Electrical Connection')

    nodes = Quantity(type=str, shape=['*'])
    type = Quantity(type=str)
    source_role = Quantity(type=str)
    raw_expression = Quantity(type=str)


class ExperimentFile(MSection):
    m_def = Section(label='Experiment File')

    path = Quantity(type=str)
    role = Quantity(type=MEnum('raw', 'intermediate', 'processed', 'figure'))


class MetadataProvenance(MSection):
    m_def = Section(label='Metadata Provenance')

    field = Quantity(type=str)
    value = Quantity(type=str)
    source_type = Quantity(type=str)
    source = Quantity(type=str)
    method = Quantity(type=str)


class LineageEdge(MSection):
    m_def = Section(label='Lineage Edge')

    source = Quantity(type=str)
    target = Quantity(type=str)
    relation = Quantity(type=str)


class IngestionReview(MSection):
    m_def = Section(label='Ingestion Review')

    warnings = Quantity(type=str, shape=['*'])
    confidence = Quantity(type=float)
    needs_review = Quantity(type=bool)


class OpticalExperiment(EntryData):
    """
    Basic metadata for an optical spectroscopy experiment.
    """

    m_def = Section(label='Optical Experiment')

    experiment_id = Quantity(
        type=str,
        description='Unique experiment identifier.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity
        ),
    )

    sample_id = Quantity(
        type=str,
        description='Sample or device identifier, e.g. D356.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity
        ),
    )

    experiment_date = Quantity(
        type=str,
        description='Experiment date, preferably YYYY-MM-DD.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity
        ),
    )

    operator = Quantity(
        type=str,
        description='Researcher who performed the experiment.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity
        ),
    )

    measurement_type = Quantity(
        type=MEnum(
            'photocurrent',
            'absorption',
            'photoluminescence',
            'reflectance',
            'pump_probe',
            'raman',
            'transport',
            'mcd',
            'other',
        ),
        description='Type of measurement.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.EnumEditQuantity
        ),
    )

    temperature = Quantity(
        type=float,
        unit='K',
        description='Sample temperature.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity
        ),
    )

    magnetic_field = Quantity(
        type=float,
        unit='T',
        description='Applied magnetic field.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity
        ),
    )

    polarization = Quantity(
        type=MEnum(
            'sigma_plus',
            'sigma_minus',
            'linear',
            'unpolarized',
            'other',
        ),
        description='Optical polarization.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.EnumEditQuantity
        ),
    )

    instrument = Quantity(
        type=str,
        description='Main instrument or acquisition software used.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.StringEditQuantity
        ),
    )

    excitation_wavelength = Quantity(
        type=float,
        unit='nm',
        description='Excitation wavelength.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity
        ),
    )

    excitation_power = Quantity(
        type=float,
        unit='uW',
        description='Excitation power.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity
        ),
    )

    grating = Quantity(
        type=float,
        unit='1/mm',
        description='Spectrometer grating groove density.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.NumberEditQuantity
        ),
    )

    raw_data_file = Quantity(
        type=str,
        description='Primary raw data file for this measurement.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity
        ),
        a_browser=BrowserAnnotation(
            adaptor='RawFileAdaptor'
        ),
    )

    processed_data_file = Quantity(
        type=str,
        description='Primary processed data file for this measurement.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.FileEditQuantity
        ),
        a_browser=BrowserAnnotation(
            adaptor='RawFileAdaptor'
        ),
    )

    notes = Quantity(
        type=str,
        description='Free-form experimental notes.',
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.RichTextEditQuantity
        ),
    )

    measurement_point_label = Quantity(type=str)

    center_wavelength = Quantity(type=float, unit='nm')

    integration_time = Quantity(type=float, unit='s')

    averages = Quantity(type=int)

    rotations = Quantity(type=float, unit='degree', shape=['*'])

    stage_position = Quantity(type=float)

    fixed_top_gate = Quantity(type=float, unit='V')

    active_gate_configuration = Quantity(type=str)

    sweep_direction = Quantity(type=str)

    bias_start = Quantity(type=float, unit='V')

    bias_stop = Quantity(type=float, unit='V')

    back_gate_topology = Quantity(type=str)

    fixed_gate_values = SubSection(sub_section=GateValue.m_def, repeats=True)

    gate_constraints = SubSection(sub_section=GateConstraint.m_def, repeats=True)

    electrical_connections = SubSection(sub_section=ElectricalConnection.m_def, repeats=True)

    files = SubSection(sub_section=ExperimentFile.m_def, repeats=True)

    metadata_provenance = SubSection(sub_section=MetadataProvenance.m_def, repeats=True)

    lineage = SubSection(sub_section=LineageEdge.m_def, repeats=True)

    ingestion_review = SubSection(sub_section=IngestionReview.m_def)


m_package.__init_metainfo__()
