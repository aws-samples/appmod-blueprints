#!/usr/bin/env node
/**
 * Check for available Helm chart updates in addons.yaml
 * Uses YAML parsing to correctly extract chart information
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const testFile = 'gitops/addons/bootstrap/default/addons.yaml';
const fullPath = path.join(__dirname, testFile);
const content = fs.readFileSync(fullPath, 'utf8');

console.log('🔍 Checking for Helm Chart Updates in addons.yaml\n');
console.log('='.repeat(80));

// Simple YAML parser for our specific structure
const lines = content.split('\n');
const charts = [];
let currentChart = {};
let inAddonBlock = false;

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];

  // Detect addon block start (no leading spaces, ends with :)
  if (/^[a-z][a-z0-9-]*:\s*$/.test(line)) {
    // Save previous chart if complete
    if (currentChart.chartName && currentChart.defaultVersion && currentChart.chartRepository) {
      if (currentChart.chartRepository.startsWith('https://')) {
        charts.push({ ...currentChart });
      }
    }
    // Start new chart
    currentChart = {
      addonName: line.replace(':', '').trim()
    };
    inAddonBlock = true;
  }
  // Extract chart properties (2 spaces indent)
  else if (inAddonBlock && /^  [a-zA-Z]/.test(line)) {
    const match = line.match(/^\s+([a-zA-Z]+):\s*(.+)$/);
    if (match) {
      const [, key, value] = match;
      if (key === 'chartName') {
        currentChart.chartName = value.trim();
      } else if (key === 'defaultVersion') {
        currentChart.defaultVersion = value.replace(/['"]/g, '').trim();
      } else if (key === 'chartRepository') {
        currentChart.chartRepository = value.replace(/['"]/g, '').trim();
      }
    }
  }
}

// Don't forget the last one
if (currentChart.chartName && currentChart.defaultVersion && currentChart.chartRepository) {
  if (currentChart.chartRepository.startsWith('https://')) {
    charts.push(currentChart);
  }
}

console.log(`\nFound ${charts.length} Helm charts with https:// repositories to check...\n`);

const results = [];
let checkCount = 0;

for (const chart of charts) {
  checkCount++;
  console.log(`${checkCount}. ${chart.addonName}`);
  console.log(`   Chart: ${chart.chartName}@${chart.defaultVersion}`);
  console.log(`   Repo: ${chart.chartRepository}`);

  try {
    // Add the Helm repo
    const repoName = `temp-check-${checkCount}`;
    execSync(`helm repo add ${repoName} "${chart.chartRepository}" 2>&1`, {
      stdio: 'pipe',
      encoding: 'utf8'
    });
    execSync(`helm repo update ${repoName} 2>&1`, { stdio: 'pipe' });

    // Search for the chart
    const searchOutput = execSync(`helm search repo ${repoName}/${chart.chartName} --versions --output json`, {
      encoding: 'utf8',
      stdio: 'pipe'
    });

    const versions = JSON.parse(searchOutput);

    // Clean up
    execSync(`helm repo remove ${repoName} 2>&1`, { stdio: 'pipe' });

    if (versions.length > 0) {
      const latestVersion = versions[0].version;
      const currentClean = chart.defaultVersion.replace(/^v/, '');
      const latestClean = latestVersion.replace(/^v/, '');

      const needsUpdate = currentClean !== latestClean;

      results.push({
        addon: chart.addonName,
        chartName: chart.chartName,
        current: chart.defaultVersion,
        latest: latestVersion,
        needsUpdate,
        repository: chart.chartRepository
      });

      if (needsUpdate) {
        console.log(`   ⚠️  UPDATE: ${chart.defaultVersion} → ${latestVersion}`);
      } else {
        console.log(`   ✅ Up to date`);
      }
    } else {
      console.log(`   ⚠️  Not found`);
      results.push({
        addon: chart.addonName,
        chartName: chart.chartName,
        current: chart.defaultVersion,
        latest: 'NOT FOUND',
        needsUpdate: false,
        repository: chart.chartRepository
      });
    }
  } catch (error) {
    console.log(`   ❌ Error checking`);
    results.push({
      addon: chart.addonName,
      chartName: chart.chartName,
      current: chart.defaultVersion,
      latest: 'ERROR',
      needsUpdate: false,
      repository: chart.chartRepository
    });
  }

  console.log();
}

console.log('='.repeat(80));
console.log('\n📊 SUMMARY\n');

const updatesAvailable = results.filter(r => r.needsUpdate);
const upToDate = results.filter(r => !r.needsUpdate && r.latest !== 'ERROR' && r.latest !== 'NOT FOUND');
const errors = results.filter(r => r.latest === 'ERROR' || r.latest === 'NOT FOUND');

console.log(`   ✅ Up to date: ${upToDate.length}`);
console.log(`   ⚠️  Updates available: ${updatesAvailable.length}`);
console.log(`   ❌ Errors/Not found: ${errors.length}`);

if (updatesAvailable.length > 0) {
  console.log('\n🔄 UPDATES AVAILABLE:\n');
  updatesAvailable.forEach((chart, i) => {
    console.log(`   ${i + 1}. ${chart.addon}`);
    console.log(`      ${chart.chartName}: ${chart.current} → ${chart.latest}`);
    console.log();
  });
  console.log('💡 Renovate will create PRs for these updates.');
}

console.log('\n' + '='.repeat(80));
