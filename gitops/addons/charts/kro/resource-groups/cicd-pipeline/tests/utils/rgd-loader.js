import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

/**
 * Load and parse the RGD YAML file
 */
export function loadRGD() {
  const rgdPath = path.resolve(process.cwd(), '../cicd-pipeline.yaml');
  const rgdContent = fs.readFileSync(rgdPath, 'utf8');
  return yaml.load(rgdContent);
}

/**
 * Create a mock schema instance for testing
 */
export function createMockSchemaInstance(overrides = {}) {
  const defaultInstance = {
    spec: {
      name: 'test-app-cicd',
      namespace: 'test-namespace',
      aws: {
        region: 'us-west-2',
        clusterName: 'test-cluster'
      },
      application: {
        name: 'test-app',
        dockerfilePath: '.',
        deploymentPath: './deployment'
      },
      ecr: {
        repositoryPrefix: 'modengg'
      },
      gitlab: {
        hostname: 'gitlab.example.com',
        username: 'testuser'
      }
    }
  };

  return mergeDeep(defaultInstance, overrides);
}

/**
 * Deep merge utility function
 */
function mergeDeep(target, source) {
  const output = Object.assign({}, target);
  if (isObject(target) && isObject(source)) {
    Object.keys(source).forEach(key => {
      if (isObject(source[key])) {
        if (!(key in target))
          Object.assign(output, { [key]: source[key] });
        else
          output[key] = mergeDeep(target[key], source[key]);
      } else {
        Object.assign(output, { [key]: source[key] });
      }
    });
  }
  return output;
}

function isObject(item) {
  return (item && typeof item === 'object' && !Array.isArray(item));
}

/**
 * Mock resource status for testing readyWhen conditions
 */
export function createMockResourceStatus(resourceId, ready = true) {
  const statusMap = {
    namespace: {
      status: { phase: ready ? 'Active' : 'Pending' }
    },
    serviceaccount: {
      status: ready ? {} : null
    },
    role: {
      status: ready ? {} : null
    },
    rolebinding: {
      status: ready ? {} : null
    },
    configmap: {
      status: ready ? {} : null
    },
    dockersecret: {
      status: ready ? {} : null
    },
    ecrrefreshcronjob: {
      status: ready ? {} : null
    },
    initialecrcredsetup: {
      status: {
        conditions: ready ? [{ type: 'Complete', status: 'True' }] : []
      }
    },
    ecrmainrepo: {
      status: {
        conditions: ready ? [{ status: 'True' }] : [{ status: 'False' }],
        repositoryURI: '123456789012.dkr.ecr.us-west-2.amazonaws.com/modengg/test-app',
        repositoryName: 'modengg/test-app',
        registryId: '123456789012',
        ackResourceMetadata: {
          arn: 'arn:aws:ecr:us-west-2:123456789012:repository/modengg/test-app'
        }
      }
    },
    ecrcacherepo: {
      status: {
        conditions: ready ? [{ status: 'True' }] : [{ status: 'False' }],
        repositoryURI: '123456789012.dkr.ecr.us-west-2.amazonaws.com/modengg/test-app/cache',
        repositoryName: 'modengg/test-app/cache',
        registryId: '123456789012',
        ackResourceMetadata: {
          arn: 'arn:aws:ecr:us-west-2:123456789012:repository/modengg/test-app/cache'
        }
      }
    },
    iampolicy: {
      status: {
        conditions: ready ? [{ status: 'True' }] : [{ status: 'False' }],
        ackResourceMetadata: {
          arn: 'arn:aws:iam::123456789012:policy/test-app-cicd-ecr-policy'
        }
      }
    },
    iamrole: {
      status: {
        conditions: ready ? [{ status: 'True' }] : [{ status: 'False' }],
        ackResourceMetadata: {
          arn: 'arn:aws:iam::123456789012:role/test-app-cicd-role',
          name: 'test-app-cicd-role'
        }
      }
    },
    rolepolicyattachment: {
      status: {
        conditions: ready ? [{ status: 'True' }] : [{ status: 'False' }],
        ackResourceMetadata: {
          arn: 'arn:aws:iam::123456789012:role/test-app-cicd-role'
        }
      }
    },
    podidentityassoc: {
      status: {
        conditions: ready ? [{ type: 'ACK.ResourceSynced', status: 'True' }] : [],
        ackResourceMetadata: {
          arn: 'arn:aws:eks:us-west-2:123456789012:podidentityassociation/test-cluster/a-12345'
        }
      }
    },
    provisioningworkflow: {
      status: ready ? {} : null
    },
    cachewarmupworkflow: {
      status: ready ? {} : null
    },
    cicdworkflow: {
      status: ready ? {} : null
    },
    cachedockerfile: {
      status: ready ? {} : null
    },
    setupworkflow: {
      status: ready ? {} : null
    },
    eventsource: {
      status: ready ? {} : null
    },
    sensor: {
      status: ready ? {} : null
    },
    webhookservice: {
      status: ready ? {} : null
    },
    webhookingress: {
      status: ready ? {} : null
    }
  };

  return statusMap[resourceId] || { status: ready ? {} : null };
}