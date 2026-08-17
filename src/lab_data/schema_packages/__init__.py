from nomad.config.models.plugins import SchemaPackageEntryPoint


class LabDataSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from lab_data.schema_packages.schema_package import m_package

        return m_package


schema_package_entry_point = LabDataSchemaPackageEntryPoint(
    name='LabDataSchema',
    description='Schema package for experimental laboratory data.',
)