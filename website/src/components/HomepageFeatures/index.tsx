import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  icon: string;
  title: string;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    icon: '🔌',
    title: 'One line per resource',
    description: (
      <>
        <code>crud_router(Company)</code> gives list, details, create, update and delete. The section
        name and URL come from your table name.
      </>
    ),
  },
  {
    icon: '🔎',
    title: 'Querying built in',
    description: (
      <>
        Filters, multi-sort, pagination and keyword search over relations, with whitelists derived from
        your model.
      </>
    ),
  },
  {
    icon: '🧪',
    title: 'Validation from your model',
    description: (
      <>
        Pydantic models generated from SQLAlchemy columns, uniqueness checks, and per-request rule
        overrides.
      </>
    ),
  },
  {
    icon: '🎬',
    title: 'Hooks everywhere',
    description: (
      <>
        Seven hooks around every action. <code>on_before_query</code> receives a real SQLAlchemy{' '}
        <code>Select</code>.
      </>
    ),
  },
  {
    icon: '📦',
    title: 'Uploads, cache, export',
    description: <>Multipart/base64 uploads with presets, TTL caching, and CSV/Excel export.</>,
  },
  {
    icon: '🔁',
    title: 'Same API as crudman-nestjs',
    description: (
      <>
        Identical query parameters and response envelope, so a front-end works against either backend.
      </>
    ),
  },
];

function Feature({icon, title, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4', 'margin-bottom--lg')}>
      <div className="text--center">
        <div className={styles.icon} aria-hidden="true">
          {icon}
        </div>
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
