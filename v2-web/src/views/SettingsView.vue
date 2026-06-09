<template>
  <section>
    <h1 class="page-title">系统设置</h1>
    <div class="panel">
      <el-form label-width="120px">
        <el-form-item label="OSS Endpoint">
          <el-input placeholder="https://oss-cn-example.aliyuncs.com" />
        </el-form-item>
        <el-form-item label="备份策略">
          <el-switch active-text="每日备份到 OSS" />
        </el-form-item>
      </el-form>
    </div>
  </section>
</template>

