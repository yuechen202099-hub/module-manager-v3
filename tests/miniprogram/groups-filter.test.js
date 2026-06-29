const assert = require('assert')

const { filterRemoteGroupsByLocalDrafts } = require('../../miniprogram/services/groups')

const remoteGroups = [
  { id: 'g-1', meter_no: '6000675027' },
  { id: 'g-2', meter_no: '6000675028' }
]

const localDrafts = [
  { groupId: 'g-1', status: 'ready' }
]

const todoGroups = filterRemoteGroupsByLocalDrafts(remoteGroups, localDrafts, 'todo')
assert.deepStrictEqual(todoGroups.map((group) => group.id), ['g-2'])

const allGroups = filterRemoteGroupsByLocalDrafts(remoteGroups, localDrafts, 'all')
assert.deepStrictEqual(allGroups.map((group) => group.id), ['g-1', 'g-2'])

