import type { App, Plugin } from 'vue'
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElDescriptions, ElDescriptionsItem } from 'element-plus/es/components/descriptions/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElDrawer } from 'element-plus/es/components/drawer/index'
import { ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus/es/components/dropdown/index'
import { ElEmpty } from 'element-plus/es/components/empty/index'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElLoading } from 'element-plus/es/components/loading/index'
import { ElOption, ElSelect } from 'element-plus/es/components/select/index'
import { ElPagination } from 'element-plus/es/components/pagination/index'
import { ElProgress } from 'element-plus/es/components/progress/index'
import { ElRadioButton, ElRadioGroup } from 'element-plus/es/components/radio/index'
import { ElSegmented } from 'element-plus/es/components/segmented/index'
import { ElSkeleton } from 'element-plus/es/components/skeleton/index'
import { ElSwitch } from 'element-plus/es/components/switch/index'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import { ElTooltip } from 'element-plus/es/components/tooltip/index'
import { provideGlobalConfig } from 'element-plus/es/components/config-provider/index'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

const components: Plugin[] = [
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElOption,
  ElPagination,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSegmented,
  ElSelect,
  ElSkeleton,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
]

export function installElementPlus(app: App) {
  for (const component of components) {
    app.use(component)
  }
  app.use(ElLoading)
  provideGlobalConfig({ locale: zhCn }, app, true)
}
