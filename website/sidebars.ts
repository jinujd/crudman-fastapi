import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    'getting-started',
    'defining-cruds',
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
      items: ['hooks', 'context', 'custom-routes', 'access-control'],
    },
    {
      type: 'category',
      label: 'More features',
      items: ['uploads', 'caching', 'import-export'],
    },
    'migrating-from-nestjs',
    'features',
    'roadmap',
  ],
};

export default sidebars;
