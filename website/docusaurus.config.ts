import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'crudman-fastapi',
  tagline: 'Zero-boilerplate CRUD for FastAPI and SQLAlchemy',
  favicon: 'img/logo.svg',

  future: {
    v4: true,
  },

  url: 'https://jinujd.github.io',
  baseUrl: '/crudman-fastapi/',
  organizationName: 'jinujd',
  projectName: 'crudman-fastapi',
  trailingSlash: false,

  onBrokenLinks: 'throw',

  // .md files are plain CommonMark (so `{id}` in text is safe); .mdx files are MDX.
  markdown: {
    format: 'detect',
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/jinujd/crudman-fastapi/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'crudman-fastapi',
      logo: {
        alt: 'CRUD Man logo',
        src: 'img/logo.svg',
      },
      items: [
        {type: 'docSidebar', sidebarId: 'docsSidebar', position: 'left', label: 'Docs'},
        {to: '/docs/features', label: 'Features', position: 'left'},
        {to: '/docs/roadmap', label: 'Roadmap', position: 'left'},
        {href: 'https://github.com/jinujd/crudman-nestjs', label: 'NestJS version', position: 'right'},
        {href: 'https://github.com/jinujd/crudman-fastapi', label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Getting started', to: '/docs/getting-started'},
            {label: 'Defining CRUDs', to: '/docs/defining-cruds'},
            {label: 'Querying', to: '/docs/querying'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/jinujd/crudman-fastapi'},
            {label: 'Issues', href: 'https://github.com/jinujd/crudman-fastapi/issues'},
            {label: 'crudman-nestjs', href: 'https://github.com/jinujd/crudman-nestjs'},
          ],
        },
      ],
      copyright: `MIT licensed. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'python', 'json'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
