#!/usr/bin/env node

/**
 * Post-install script to apply GitLab timeout fix
 * Run this after yarn install to patch the GitLab scaffolder module
 */

const fs = require('fs');
const path = require('path');

const GITLAB_MODULE_PATH = 'node_modules/@backstage/plugin-scaffolder-backend-module-gitlab/dist/actions/gitlab.js';

console.log('🔧 Applying GitLab timeout fix...');

try {
  if (!fs.existsSync(GITLAB_MODULE_PATH)) {
    console.log('❌ GitLab module not found. Make sure you run yarn install first.');
    process.exit(1);
  }

  let content = fs.readFileSync(GITLAB_MODULE_PATH, 'utf8');

  // Check if already patched
  if (content.includes('gitTimeout')) {
    console.log('✅ GitLab timeout fix already applied!');
    process.exit(0);
  }

  // Add gitTimeout to schema
  const schemaPattern = /token: z =>\s*z\s*\.string\(\{\s*description: 'The token to use for authorization to GitLab',\s*\}\)\s*\.optional\(\),/;
  
  if (schemaPattern.test(content)) {
    content = content.replace(
      schemaPattern,
      `token: z =>
          z
            .string({
              description: 'The token to use for authorization to GitLab',
            })
            .optional(),
        gitTimeout: z =>
          z
            .number({
              description: 'Timeout in seconds for git operations (default: 60)',
            })
            .optional(),`
    );
  }

  // Add gitTimeout to destructuring
  const destructuringPattern = /(signCommit,)\s*} = ctx\.input;/;
  
  if (destructuringPattern.test(content)) {
    content = content.replace(
      destructuringPattern,
      `$1
        gitTimeout = 60,
      } = ctx.input;`
    );
  }

  // Replace initRepoAndPush call with timeout
  const initRepoPattern = /const commitResult = await initRepoAndPush\(\{([^}]+)\}\);/s;
  
  if (initRepoPattern.test(content)) {
    content = content.replace(
      initRepoPattern,
      `// Wrap initRepoAndPush with timeout
          const pushWithTimeout = new Promise((resolve, reject) => {
            const timeoutId = setTimeout(() => {
              reject(new Error(\`Git push operation timed out after \${gitTimeout} seconds\`));
            }, gitTimeout * 1000);

            initRepoAndPush({$1}).then((result) => {
              clearTimeout(timeoutId);
              resolve(result);
            }).catch((error) => {
              clearTimeout(timeoutId);
              reject(error);
            });
          });

          const commitResult = await pushWithTimeout;`
    );
  }

  // Write the patched content
  fs.writeFileSync(GITLAB_MODULE_PATH, content);
  
  console.log('✅ GitLab timeout fix applied successfully!');
  console.log('');
  console.log('You can now use gitTimeout parameter in your templates:');
  console.log('  gitTimeout: 120  # timeout in seconds');
  
} catch (error) {
  console.error('❌ Failed to apply GitLab timeout fix:', error.message);
  process.exit(1);
}