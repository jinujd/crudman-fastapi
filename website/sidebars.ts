import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    'getting-started',
    'defining-cruds',
    'controllers',
    {
      type: 'category',
      label: 'Configuration',
      collapsed: false,
      items: ['sections', 'querying', 'validation', 'response-format'],
    },
    {
      type: 'category',
      label: 'Extending',
      collapsed: false,
      items: ['authentication', 'access-control', 'hooks', 'context', 'custom-routes'],
    },
    {
      type: 'category',
      label: 'More features',
      items: ['uploads', 'caching', 'import-export'],
    },
    'security',
    'migrating-from-nestjs',
    'features',
    'roadmap',
  ],
};

export default sidebars;
