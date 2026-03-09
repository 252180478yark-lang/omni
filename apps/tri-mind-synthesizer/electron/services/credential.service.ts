/**
 * 凭据服务
 * 
 * 使用 keytar 调用系统凭据管理器安全存储 API Key：
 * - Windows: Windows Credential Locker (凭据管理器)
 * - macOS: Keychain
 * - Linux: libsecret
 * 
 * 如果 keytar 不可用（如沙箱环境），
 * 降级到 AES-256-GCM 加密文件存储。
 */

import crypto from 'crypto'
import fs from 'fs'
import path from 'path'
import { app } from 'electron'

const SERVICE_NAME = 'tri-mind-synthesizer'

// 内存缓存
const credentialCache = new Map<string, string>()

// keytar 实例（延迟加载）
let keytarModule: typeof import('keytar') | null = null
let keytarAvailable: boolean | null = null

/**
 * 尝试加载 keytar 模块
 */
async function getKeytar(): Promise<typeof import('keytar') | null> {
  if (keytarAvailable === false) return null
  
  if (keytarModule) return keytarModule

  try {
    // keytar 是原生模块，需要动态导入
    keytarModule = require('keytar')
    keytarAvailable = true
    console.log('凭据服务: 使用系统凭据管理器 (keytar)')
    return keytarModule
  } catch (error) {
    console.warn('凭据服务: keytar 不可用，降级到加密文件存储:', error)
    keytarAvailable = false
    return null
  }
}

// ==================== keytar 接口 ====================

async function keytarSave(provider: string, apiKey: string): Promise<boolean> {
  const keytar = await getKeytar()
  if (!keytar) return false
  
  try {
    await keytar.setPassword(SERVICE_NAME, provider, apiKey)
    return true
  } catch (error) {
    console.error('keytar 保存失败:', error)
    return false
  }
}

async function keytarGet(provider: string): Promise<string | null> {
  const keytar = await getKeytar()
  if (!keytar) return null
  
  try {
    return await keytar.getPassword(SERVICE_NAME, provider)
  } catch (error) {
    console.error('keytar 读取失败:', error)
    return null
  }
}

async function keytarDelete(provider: string): Promise<boolean> {
  const keytar = await getKeytar()
  if (!keytar) return false
  
  try {
    return await keytar.deletePassword(SERVICE_NAME, provider)
  } catch (error) {
    console.error('keytar 删除失败:', error)
    return false
  }
}

// ==================== 降级方案: 加密文件存储 ====================

function getCredentialPath(): string {
  const userDataPath = app.getPath('userData')
  return path.join(userDataPath, '.credentials')
}

function getDerivedKey(): Buffer {
  const machineId = `${process.env.COMPUTERNAME || process.env.HOSTNAME || 'default'}-${SERVICE_NAME}`
  return crypto.pbkdf2Sync(machineId, SERVICE_NAME, 100000, 32, 'sha512')
}

function encrypt(text: string): string {
  const key = getDerivedKey()
  const iv = crypto.randomBytes(16)
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv)
  const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()])
  const authTag = cipher.getAuthTag()
  
  return JSON.stringify({
    iv: iv.toString('hex'),
    data: encrypted.toString('hex'),
    tag: authTag.toString('hex'),
  })
}

function decrypt(encryptedJson: string): string {
  const { iv, data, tag } = JSON.parse(encryptedJson)
  const key = getDerivedKey()
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(iv, 'hex'))
  decipher.setAuthTag(Buffer.from(tag, 'hex'))
  return decipher.update(Buffer.from(data, 'hex')) + decipher.final('utf8')
}

function readCredentials(): Record<string, string> {
  try {
    const credPath = getCredentialPath()
    if (!fs.existsSync(credPath)) return {}
    
    const content = fs.readFileSync(credPath, 'utf-8')
    const decrypted = decrypt(content)
    return JSON.parse(decrypted)
  } catch (error) {
    console.error('读取凭据文件失败:', error)
    return {}
  }
}

function writeCredentials(credentials: Record<string, string>): void {
  try {
    const credPath = getCredentialPath()
    const dir = path.dirname(credPath)
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true })
    }
    
    const encrypted = encrypt(JSON.stringify(credentials))
    fs.writeFileSync(credPath, encrypted, 'utf-8')
  } catch (error) {
    console.error('写入凭据文件失败:', error)
  }
}

// ==================== 公共 API ====================

/**
 * 保存 API Key
 * 优先使用系统凭据管理器，不可用时降级到加密文件
 */
export async function saveApiKey(provider: string, apiKey: string): Promise<void> {
  // 更新内存缓存
  credentialCache.set(provider, apiKey)
  
  // 优先尝试 keytar
  const saved = await keytarSave(provider, apiKey)
  
  if (!saved) {
    // 降级到加密文件
    const credentials = readCredentials()
    credentials[provider] = apiKey
    writeCredentials(credentials)
  }
  
  console.log(`API Key 已保存: ${provider} (${saved ? 'keytar' : '加密文件'})`)
}

/**
 * 获取 API Key
 */
export async function getApiKey(provider: string): Promise<string | null> {
  // 先查缓存
  if (credentialCache.has(provider)) {
    return credentialCache.get(provider) || null
  }

  // 优先从 keytar 读取
  let apiKey = await keytarGet(provider)
  
  // 降级到加密文件
  if (apiKey === null) {
    const credentials = readCredentials()
    apiKey = credentials[provider] || null
  }
  
  if (apiKey) {
    credentialCache.set(provider, apiKey)
  }
  
  return apiKey
}

/**
 * 删除 API Key
 */
export async function deleteApiKey(provider: string): Promise<void> {
  credentialCache.delete(provider)
  
  // 从 keytar 删除
  await keytarDelete(provider)
  
  // 同时从加密文件中删除
  const credentials = readCredentials()
  delete credentials[provider]
  writeCredentials(credentials)
  
  console.log(`API Key 已删除: ${provider}`)
}

/**
 * 检查 API Key 是否已设置
 */
export async function hasApiKey(provider: string): Promise<boolean> {
  const apiKey = await getApiKey(provider)
  return apiKey !== null && apiKey.length > 0
}

/**
 * 获取所有已保存的提供商列表
 */
export async function listProviders(): Promise<string[]> {
  // 合并 keytar 和文件中的提供商
  const fileProviders = Object.keys(readCredentials())
  const cachedProviders = Array.from(credentialCache.keys())
  return [...new Set([...fileProviders, ...cachedProviders])]
}

/**
 * 清除所有缓存
 */
export function clearCache(): void {
  credentialCache.clear()
}
