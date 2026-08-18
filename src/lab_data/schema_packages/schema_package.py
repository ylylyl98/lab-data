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

    fixed_gate_values = SubSection(sub_section=GateValue.m_def, repeats=True)


m_package.__init_metainfo__()
